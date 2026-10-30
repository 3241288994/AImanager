//! Metadata-only device coordination. OAuth credentials never cross this API.
//! The Mac worker calls heartbeat through its existing, verified SSH connection.
use codexmanager_core::{auth::{parse_id_token_claims, extract_workspace_id}, storage::now_ts};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::sync::Mutex;

const KEY: &str = "codex_profile.devices";
const MAX_AGE: i64 = 86400;
static LOCK: Mutex<()> = Mutex::new(());

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct DeviceTask {
    pub request_id: String,
    pub parent_request_id: Option<String>,
    pub account_id: String,
    pub kind: String,
    pub state: String,
    pub reason: String,
    pub requested_at: i64,
    pub updated_at: i64,
    pub verification_url: Option<String>,
    pub user_code: Option<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct Device {
    pub id: String,
    pub label: String,
    pub last_seen_at: i64,
    pub current_account_id: Option<String>,
    pub known_account_ids: Vec<String>,
    pub task: Option<DeviceTask>,
}

fn load() -> Result<Vec<Device>,String> {
    let storage=crate::storage_helpers::open_storage().ok_or("storage unavailable")?;
    match storage.get_app_setting(KEY).map_err(|_| "read device registry failed")? {
        Some(raw) if !raw.trim().is_empty() => serde_json::from_str(&raw).map_err(|_| "device registry is invalid".into()),
        _ => Ok(vec![]),
    }
}
fn save(devices: &[Device]) -> Result<(), String> {
    let raw = serde_json::to_string(devices).map_err(|_| "serialize devices failed")?;
    let storage=crate::storage_helpers::open_storage().ok_or("storage unavailable")?;
    storage.set_app_setting(KEY,&raw,now_ts()).map_err(|_| "save device registry failed".into())
}
pub(crate) fn status() -> Result<Vec<Device>, String> { load() }

fn identity(account_id: &str) -> Result<Value, String> {
    let storage = crate::storage_helpers::open_storage().ok_or("storage unavailable")?;
    let account = storage.find_account_by_id(account_id).map_err(|_| "read account failed")?.ok_or("account not found")?;
    let token = storage.find_token_by_account_id(account_id).map_err(|_| "read identity failed")?.ok_or("account credentials missing")?;
    let claims = parse_id_token_claims(&token.id_token).map_err(|_| "account identity unavailable")?;
    let chatgpt = account.chatgpt_account_id.or_else(|| claims.auth.and_then(|a| a.chatgpt_account_id)).ok_or("account ID missing")?;
    let workspace = account.workspace_id.or_else(|| extract_workspace_id(&token.id_token)).unwrap_or_else(|| chatgpt.clone());
    if claims.sub.is_empty() { return Err("account subject missing".into()); }
    Ok(json!({"accountId":account_id,"subject":claims.sub,"chatgptAccountId":chatgpt,"workspaceId":workspace,"email":claims.email}))
}
fn identities() -> Vec<Value> {
    let Some(storage) = crate::storage_helpers::open_storage() else { return vec![]; };
    let Ok(accounts) = storage.list_accounts() else { return vec![]; };
    accounts.iter().filter(|a| a.status == "active").take(64)
        .filter_map(|a| identity(&a.id).ok()).collect()
}

fn new_task(account_id: &str, parent: Option<&str>, kind: &str) -> DeviceTask {
    DeviceTask { request_id:codexmanager_core::auth::generate_state(), parent_request_id:parent.map(str::to_owned), account_id:account_id.into(),
        kind:kind.into(), state:"pending".into(), reason:"queued".into(), requested_at:now_ts(), updated_at:now_ts(), verification_url:None, user_code:None }
}

pub(crate) fn queue_switch(parent: &str, account_id: &str) -> Result<(), String> {
    let _guard = LOCK.lock().map_err(|_| "device coordinator unavailable")?;
    let mut devices = load()?;
    for device in &mut devices { device.task = Some(new_task(account_id, Some(parent), "switch")); }
    save(&devices)
}
pub(crate) fn cancel_parent(parent: &str) -> Result<(), String> {
    let _guard = LOCK.lock().map_err(|_| "device coordinator unavailable")?;
    let mut devices = load()?;
    for device in &mut devices {
        if let Some(task) = device.task.as_mut().filter(|t| t.parent_request_id.as_deref() == Some(parent) && !terminal(&t.state)) {
            task.state = "cancelled".into(); task.reason = "cancelled".into(); task.updated_at = now_ts();
            task.user_code = None; task.verification_url = None;
        }
    }
    save(&devices)
}
pub(crate) fn login(device_id: Option<&str>, account_id: Option<&str>) -> Result<Vec<Device>, String> {
    let id = device_id.ok_or("missing deviceId")?;
    let account = account_id.ok_or("missing accountId")?;
    identity(account)?;
    let _guard = LOCK.lock().map_err(|_| "device coordinator unavailable")?;
    let mut devices = load()?;
    let device = devices.iter_mut().find(|d| d.id == id).ok_or("device is not paired")?;
    let parent = device.task.as_ref().filter(|t| t.account_id == account && !terminal(&t.state)).and_then(|t| t.parent_request_id.clone());
    device.task = Some(new_task(account, parent.as_deref(), "login"));
    save(&devices)?; Ok(devices)
}

fn terminal(state: &str) -> bool { matches!(state, "completed" | "cancelled" | "failed" | "attention") }
fn valid_id(id: &str) -> bool { (16..=64).contains(&id.len()) && id.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-') }

fn apply_report(task: &mut DeviceTask, report: &Value, known: &[String], current: Option<&str>) {
    if report.get("requestId").and_then(Value::as_str) != Some(&task.request_id) || terminal(&task.state) { return; }
    let state = report.get("state").and_then(Value::as_str).unwrap_or("");
    let reason = report.get("reason").and_then(Value::as_str).unwrap_or("");
    if !["pending","needs_login","authorizing","completed","failed","attention"].contains(&state)
        || !["queued","sessions_loaded","background_unreachable","needs_login","awaiting_approval","authorized","applied","profile_changed","identity_mismatch","credentials_invalid","network_unavailable","login_failed","profile_unavailable","background_unverified"].contains(&reason) { return; }
    if state == "completed" && (if task.parent_request_id.is_some() || task.kind == "switch" { current != Some(task.account_id.as_str()) } else { !known.contains(&task.account_id) }) { return; }
    task.state = state.into(); task.reason = reason.into(); task.updated_at = now_ts();
    task.user_code = None; task.verification_url = None;
    if state == "authorizing" && task.kind == "login" {
        let code = report.get("userCode").and_then(Value::as_str).unwrap_or("");
        let url = report.get("verificationUrl").and_then(Value::as_str).unwrap_or("");
        if (4..=24).contains(&code.len()) && code.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-') && url == "https://auth.openai.com/codex/device" {
            task.user_code = Some(code.into()); task.verification_url = Some(url.into());
        }
    }
}

/// Administrator-only worker protocol; SSH transports identifiers and task state,
/// never refresh/access/ID tokens. No browser command maps to this endpoint.
pub(crate) fn heartbeat(params: &Value) -> Result<Value, String> {
    let id = params.get("deviceId").and_then(Value::as_str).filter(|s| valid_id(s)).ok_or("invalid deviceId")?;
    let known_identities = identities();
    let _guard = LOCK.lock().map_err(|_| "device coordinator unavailable")?;
    let mut devices = load()?;
    if !devices.iter().any(|d| d.id == id) {
        if devices.len() >= 4 { return Err("at most four devices can be paired".into()); }
        devices.push(Device { id:id.into(), label:"本机 Mac".into(), last_seen_at:0, current_account_id:None, known_account_ids:vec![], task:None });
    }
    let device = devices.iter_mut().find(|d| d.id == id).unwrap();
    device.last_seen_at = now_ts();
    let ids:Vec<String> = known_identities.iter().filter_map(|x| x.get("accountId").and_then(Value::as_str).map(str::to_owned)).collect();
    device.known_account_ids = params.get("knownAccountIds").and_then(Value::as_array).map(|a| a.iter().filter_map(Value::as_str).filter(|s| ids.iter().any(|id| id == s)).take(64).map(str::to_owned).collect()).unwrap_or_default();
    device.current_account_id = params.get("currentAccountId").and_then(Value::as_str).filter(|s| ids.iter().any(|id| id == s)).map(str::to_owned);
    if let Some(task) = &mut device.task {
        if !terminal(&task.state) && now_ts().saturating_sub(task.requested_at) > MAX_AGE {
            task.state = "failed".into(); task.reason = "expired".into(); task.user_code = None; task.verification_url = None;
        }
        if let Some(report) = params.get("report") { apply_report(task, report, &device.known_account_ids, device.current_account_id.as_deref()); }
    }
    let task = device.task.clone();
    save(&devices)?;
    Ok(json!({"task":task,"identities":known_identities,"pollSeconds":2}))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn stale_ack_cannot_complete_or_leak_secrets_into_the_new_task() {
        let mut task = new_task("target",Some("root"),"switch");
        apply_report(&mut task,&json!({"requestId":"old","state":"completed","reason":"applied","accessToken":"secret"}),&[],Some("target"));
        assert_eq!(task.state,"pending"); assert!(!serde_json::to_string(&task).unwrap().contains("secret"));
        let id=task.request_id.clone();
        apply_report(&mut task,&json!({"requestId":id,"state":"completed","reason":"applied"}),&[],Some("other"));
        assert_eq!(task.state,"pending");
        apply_report(&mut task,&json!({"requestId":id,"state":"completed","reason":"applied"}),&[],Some("target"));
        assert_eq!(task.state,"completed");
    }
    #[test]
    fn otp_is_only_available_for_an_explicit_login_on_the_official_origin() {
        let mut task=new_task("target",None,"login"); let id=task.request_id.clone();
        apply_report(&mut task,&json!({"requestId":id,"state":"authorizing","reason":"awaiting_approval","verificationUrl":"https://evil.invalid","userCode":"TEST-CODE"}),&[],None);
        assert!(task.user_code.is_none());
        apply_report(&mut task,&json!({"requestId":id,"state":"authorizing","reason":"awaiting_approval","verificationUrl":"https://auth.openai.com/codex/device","userCode":"TEST-CODE"}),&[],None);
        assert_eq!(task.user_code.as_deref(),Some("TEST-CODE"));
        apply_report(&mut task,&json!({"requestId":id,"state":"completed","reason":"authorized"}),&["target".into()],None);
        assert!(task.user_code.is_none());
    }
}
