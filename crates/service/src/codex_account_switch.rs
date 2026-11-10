//! One durable, cancellable switch intent per service. No credentials in the queue.
//! All profile writers serialize through LOCK; the old account remains selected
//! while active Codex tasks prevent a safe switch.
use crate::{
    codex_daemon_sync::{self, Readiness},
    codex_profile::{self, CodexProfileStatus},
};
use codexmanager_core::storage::now_ts;
use serde::{Deserialize, Serialize};
use std::{
    path::Path,
    sync::{Mutex, Once},
    time::Duration,
};

pub(crate) static LOCK: Mutex<()> = Mutex::new(());
const KEY: &str = "codex_profile.account_switch";
const MAX_AGE: i64 = 24 * 60 * 60;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct SwitchStatus {
    #[serde(default)]
    pub sync_devices: bool,
    #[serde(default)]
    pub last_activation_at: i64,
    pub request_id: String,
    pub account_id: String,
    pub previous_account_id: Option<String>,
    pub previous_actual_account_id: Option<String>,
    pub codex_home: String,
    pub state: String,
    pub reason: String,
    pub requested_at: i64,
    pub updated_at: i64,
}

fn load() -> Option<SwitchStatus> {
    crate::app_settings::get_persisted_app_setting(KEY)
        .and_then(|raw| serde_json::from_str(&raw).ok())
}

fn save(value: &SwitchStatus) -> Result<(), String> {
    let raw = serde_json::to_string(value).map_err(|e| e.to_string())?;
    crate::app_settings::save_persisted_app_setting(KEY, Some(&raw))
}

pub(crate) fn clear_locked() -> Result<(), String> {
    if let Some(intent) = load().filter(|s| s.sync_devices) { crate::codex_devices::cancel_parent(&intent.request_id)?; }
    crate::app_settings::save_persisted_app_setting(KEY, None)
}

pub(crate) fn status(profile: &Path) -> Option<SwitchStatus> {
    load().filter(|s| Path::new(&s.codex_home) == profile)
}

pub(crate) fn request(
    account_id: Option<&str>,
    home: Option<&str>,
) -> Result<CodexProfileStatus, String> {
    request_scoped(account_id, home, false)
}

pub(crate) fn request_scoped(account_id: Option<&str>, home: Option<&str>, sync_devices: bool) -> Result<CodexProfileStatus, String> {
    let _guard = LOCK
        .try_lock()
        .map_err(|_| "another Codex account activation is in progress; retry after it completes")?;
    let id = account_id
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .ok_or("missing accountId")?;
    let profile = codex_profile::get_status(home)?;
    if profile.selected_account_id.is_some() && !profile.identity_consistent {
        return Err(
            "current profile identity changed outside AImanager; verify it before switching".into(),
        );
    }
    // Repeated clicks/network retries keep the same in-flight authorization and
    // cancellation scope. Failed/cancelled requests still permit a deliberate retry.
    if let Some(old) = load().filter(|s| s.account_id == id && s.codex_home == profile.codex_home && s.sync_devices == sync_devices) {
        let device_pending = sync_devices && crate::codex_devices::status()?.iter().any(|d| {
            d.task.as_ref().is_some_and(|t| t.parent_request_id.as_deref() == Some(old.request_id.as_str())
                && matches!(t.state.as_str(), "pending" | "needs_login" | "authorizing"))
        });
        if retryable(&old) || (old.state == "completed" && device_pending) { return Ok(profile); }
    }
    codex_profile::validate_switch_target(id)?;
    if let Some(old) = load().filter(|s| s.sync_devices) { crate::codex_devices::cancel_parent(&old.request_id)?; }
    let intent = SwitchStatus {
        sync_devices,
        last_activation_at: 0,
        request_id: codexmanager_core::auth::generate_state(),
        account_id: id.into(),
        previous_account_id: profile.selected_account_id.clone(),
        previous_actual_account_id: profile.actual_account_id.clone(),
        codex_home: profile.codex_home,
        state: "pending".into(),
        reason: "checking".into(),
        requested_at: now_ts(),
        updated_at: now_ts(),
    };
    save(&intent)?; // Latest explicitly requested target replaces the previous intent.
    if sync_devices {
        if let Err(error) = crate::codex_devices::queue_switch(&intent.request_id, id) {
            let mut failed = intent.clone();
            transition(&mut failed, "failed", "device_coordinator_unavailable")?;
            return Err(error);
        }
    }
    advance(intent)?;
    codex_profile::get_status(home)
}

pub(crate) fn cancel(request_id: Option<&str>) -> Result<CodexProfileStatus, String> {
    let _guard = LOCK
        .try_lock()
        .map_err(|_| "account activation is in progress; refresh its status before cancelling")?;
    let intent = load().ok_or("no account switch to cancel")?;
    if Some(intent.request_id.as_str()) != request_id {
        return Err("switch request changed; refresh before cancelling".into());
    }
    clear_locked()?;
    codex_profile::get_status(Some(&intent.codex_home))
}

fn gate(
    intent: &SwitchStatus,
    home: &str,
    selected: Option<&str>,
    actual: Option<&str>,
    now: i64,
) -> Result<(), &'static str> {
    if now.saturating_sub(intent.requested_at) >= MAX_AGE {
        return Err("expired");
    }
    if home != intent.codex_home
        || selected != intent.previous_account_id.as_deref()
        || actual != intent.previous_actual_account_id.as_deref()
    {
        return Err("profile_changed");
    }
    Ok(())
}

fn transition(intent: &mut SwitchStatus, state: &str, reason: &str) -> Result<(), String> {
    if intent.state != state || intent.reason != reason {
        intent.state = state.into();
        intent.reason = reason.into();
        intent.updated_at = now_ts();
        save(intent)?;
    }
    Ok(())
}

fn advance(mut intent: SwitchStatus) -> Result<(), String> {
    if !retryable(&intent) {
        return Ok(());
    }
    if now_ts().saturating_sub(intent.requested_at) >= MAX_AGE {
        return transition(&mut intent, "failed", "expired");
    }
    let profile = match codex_profile::get_status(Some(&intent.codex_home)) {
        Ok(profile) => profile,
        Err(_) => return transition(&mut intent, "failed", "credentials_or_profile"),
    };
    if profile.identity_consistent && profile.selected_account_id.as_deref() == Some(&intent.account_id)
        && codex_profile::direct_background_matches(&intent.account_id, Path::new(&intent.codex_home)) {
        return transition(&mut intent, "completed", "applied");
    }
    // Once the target is on disk, only activate the daemon. Never rewrite or
    // refresh credentials again merely because background verification lagged.
    if profile.identity_consistent && profile.selected_account_id.as_deref() == Some(&intent.account_id) {
        if now_ts().saturating_sub(intent.last_activation_at) < 15 { return Ok(()); }
        intent.last_activation_at = now_ts();
        save(&intent)?;
        let verified = codex_profile::activate_direct_background(&intent.account_id, Path::new(&intent.codex_home));
        return transition(&mut intent, if verified { "completed" } else { "pending" }, if verified { "applied" } else { "background_unverified" });
    }
    if intent.last_activation_at > 0 || (intent.state == "attention" && intent.reason == "background_unverified") {
        return transition(&mut intent, "failed", "profile_changed");
    }
    if let Err(reason) = gate(
        &intent,
        &profile.codex_home,
        profile.selected_account_id.as_deref(),
        profile.actual_account_id.as_deref(),
        now_ts(),
    ) {
        return transition(&mut intent, "failed", reason);
    }
    // Target validation and a second daemon check also happen immediately before
    // writing. Auth refresh can take time; a session may have started meanwhile.
    let (state, reason) = attempt(
        codex_daemon_sync::before_profile_write(Path::new(&intent.codex_home)),
        || {
            codex_profile::apply_direct_account_now(
                Some(&intent.account_id),
                Some(&intent.codex_home),
            )
            .map(|profile| profile.warnings.is_empty())
        },
    );
    if reason == "background_unverified" {
        intent.last_activation_at = now_ts();
        save(&intent)?;
    }
    transition(&mut intent, state, reason)
}

fn retryable(intent: &SwitchStatus) -> bool {
    intent.state == "pending" || (intent.state == "attention" && intent.reason == "background_unverified")
}

fn attempt(
    readiness: Readiness,
    apply: impl FnOnce() -> Result<bool, String>,
) -> (&'static str, &'static str) {
    match readiness {
        Readiness::Busy => return ("pending", "sessions_loaded"),
        Readiness::Unknown => return ("pending", "background_unreachable"),
        Readiness::Ready => {}
    }
    match apply() {
        Ok(true) => ("completed", "applied"),
        Ok(false) => ("pending", "background_unverified"),
        Err(error) if error == "codex_background_busy" => ("pending", "sessions_loaded"),
        Err(error) if error == "codex_background_unreachable" => {
            ("pending", "background_unreachable")
        }
        // Stop automatic retries after a credential/profile failure; reauthorization
        // or a deliberate retry is needed. Never persist raw upstream responses.
        Err(_) => ("failed", "credentials_or_profile"),
    }
}

pub(crate) fn start_worker() {
    static START: Once = Once::new();
    START.call_once(|| {
        std::thread::spawn(|| loop {
            std::thread::sleep(Duration::from_secs(2));
            let Ok(_guard) = LOCK.try_lock() else {
                continue;
            };
            if let Some(intent) = load().filter(retryable) {
                if advance(intent).is_err() {
                    log::warn!("Codex pending switch could not be processed; intent retained");
                }
            }
        });
    });
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn queue_contains_only_intent_and_survives_serialization() {
        let intent = SwitchStatus {
            sync_devices: false,
            last_activation_at: 0,
            request_id: "one".into(),
            account_id: "b".into(),
            previous_account_id: Some("a".into()),
            previous_actual_account_id: Some("a".into()),
            codex_home: "/test".into(),
            state: "pending".into(),
            reason: "sessions_loaded".into(),
            requested_at: 1,
            updated_at: 1,
        };
        let raw = serde_json::to_string(&intent).unwrap();
        assert!(!raw.contains("token"));
        assert_eq!(
            serde_json::from_str::<SwitchStatus>(&raw)
                .unwrap()
                .previous_account_id
                .as_deref(),
            Some("a")
        );
        assert!(gate(&intent, "/test", Some("a"), Some("a"), 2).is_ok());
        assert_eq!(
            gate(&intent, "/test", Some("b"), Some("a"), 2),
            Err("profile_changed")
        );
        assert_eq!(
            gate(&intent, "/other", Some("a"), Some("a"), 2),
            Err("profile_changed")
        );
        assert_eq!(
            gate(&intent, "/test", Some("a"), Some("b"), 2),
            Err("profile_changed")
        );
        assert_eq!(
            gate(&intent, "/test", Some("a"), Some("a"), MAX_AGE + 1),
            Err("expired")
        );
    }
    #[test]
    fn loaded_or_unknown_daemons_never_write_profile_or_refresh_target() {
        assert_eq!(
            attempt(Readiness::Busy, || panic!("must not apply")),
            ("pending", "sessions_loaded")
        );
        assert_eq!(
            attempt(Readiness::Unknown, || panic!("must not apply")),
            ("pending", "background_unreachable")
        );
    }
    #[test]
    fn ready_switches_distinguish_completion_uncertainty_failure_and_late_sessions() {
        assert_eq!(
            attempt(Readiness::Ready, || Ok(true)),
            ("completed", "applied")
        );
        assert_eq!(
            attempt(Readiness::Ready, || Ok(false)),
            ("pending", "background_unverified")
        );
        assert_eq!(
            attempt(Readiness::Ready, || Err("secret upstream response".into())),
            ("failed", "credentials_or_profile")
        );
        assert_eq!(
            attempt(Readiness::Ready, || Err("codex_background_busy".into())),
            ("pending", "sessions_loaded")
        );
    }
}
