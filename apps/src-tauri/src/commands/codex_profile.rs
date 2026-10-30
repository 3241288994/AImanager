use crate::commands::shared::rpc_call_in_background;

#[tauri::command]
pub async fn service_codex_devices_status(addr: Option<String>) -> Result<serde_json::Value,String> {
    rpc_call_in_background("codexDevices/status",addr,None).await
}
#[tauri::command]
pub async fn service_codex_devices_login(addr: Option<String>,device_id:String,account_id:String) -> Result<serde_json::Value,String> {
    rpc_call_in_background("codexDevices/login",addr,Some(serde_json::json!({"deviceId":device_id,"accountId":account_id}))).await
}

#[tauri::command]
pub async fn service_codex_profile_cancel_switch(addr: Option<String>, request_id: String) -> Result<serde_json::Value, String> {
    rpc_call_in_background("codexProfile/cancelSwitch", addr, Some(serde_json::json!({"requestId": request_id}))).await
}

/// 函数 `service_codex_profile_get`
///
/// 作者: gaohongshun
///
/// 时间: 2026-04-02
///
/// # 参数
/// - addr: 参数 addr
/// - codex_home: 参数 codex_home
///
/// # 返回
/// 返回函数执行结果
#[tauri::command]
pub async fn service_codex_profile_get(
    addr: Option<String>,
    codex_home: Option<String>,
) -> Result<serde_json::Value, String> {
    let params = serde_json::json!({ "codexHome": codex_home });
    rpc_call_in_background("codexProfile/get", addr, Some(params)).await
}

/// 函数 `service_codex_profile_set_config`
///
/// 作者: gaohongshun
///
/// 时间: 2026-04-02
///
/// # 参数
/// - addr: 参数 addr
/// - codex_home: 参数 codex_home
///
/// # 返回
/// 返回函数执行结果
#[tauri::command]
pub async fn service_codex_profile_set_config(
    addr: Option<String>,
    codex_home: Option<String>,
) -> Result<serde_json::Value, String> {
    let params = serde_json::json!({ "codexHome": codex_home });
    rpc_call_in_background("codexProfile/setConfig", addr, Some(params)).await
}

/// 函数 `service_codex_profile_list_candidates`
///
/// 作者: gaohongshun
///
/// 时间: 2026-04-02
///
/// # 参数
/// - addr: 参数 addr
///
/// # 返回
/// 返回函数执行结果
#[tauri::command]
pub async fn service_codex_profile_list_candidates(
    addr: Option<String>,
) -> Result<serde_json::Value, String> {
    rpc_call_in_background("codexProfile/listCandidates", addr, None).await
}

/// 函数 `service_codex_profile_apply_direct_account`
///
/// 作者: gaohongshun
///
/// 时间: 2026-04-02
///
/// # 参数
/// - addr: 参数 addr
/// - account_id: 参数 account_id
/// - codex_home: 参数 codex_home
///
/// # 返回
/// 返回函数执行结果
#[tauri::command]
pub async fn service_codex_profile_apply_direct_account(
    addr: Option<String>,
    account_id: String,
    codex_home: Option<String>,
    sync_devices: Option<bool>,
) -> Result<serde_json::Value, String> {
    let params = serde_json::json!({
        "accountId": account_id,
        "codexHome": codex_home,
        "syncDevices": sync_devices.unwrap_or(false),
    });
    rpc_call_in_background("codexProfile/applyDirectAccount", addr, Some(params)).await
}

/// 函数 `service_codex_profile_apply_gateway`
///
/// 作者: gaohongshun
///
/// 时间: 2026-04-02
///
/// # 参数
/// - addr: 参数 addr
/// - api_key_id: 参数 api_key_id
/// - codex_home: 参数 codex_home
/// - base_url: 参数 base_url
///
/// # 返回
/// 返回函数执行结果
#[tauri::command]
pub async fn service_codex_profile_apply_gateway(
    addr: Option<String>,
    api_key_id: String,
    codex_home: Option<String>,
    base_url: Option<String>,
) -> Result<serde_json::Value, String> {
    let params = serde_json::json!({
        "apiKeyId": api_key_id,
        "codexHome": codex_home,
        "baseUrl": base_url,
    });
    rpc_call_in_background("codexProfile/applyGateway", addr, Some(params)).await
}

/// 函数 `service_codex_profile_restore`
///
/// 作者: gaohongshun
///
/// 时间: 2026-04-02
///
/// # 参数
/// - addr: 参数 addr
/// - codex_home: 参数 codex_home
///
/// # 返回
/// 返回函数执行结果
#[tauri::command]
pub async fn service_codex_profile_restore(
    addr: Option<String>,
    codex_home: Option<String>,
) -> Result<serde_json::Value, String> {
    let params = serde_json::json!({ "codexHome": codex_home });
    rpc_call_in_background("codexProfile/restore", addr, Some(params)).await
}

/// 函数 `service_codex_profile_repair_history`
///
/// 作者: gaohongshun
///
/// 时间: 2026-04-02
///
/// # 参数
/// - addr: 参数 addr
/// - codex_home: 参数 codex_home
///
/// # 返回
/// 返回函数执行结果
#[tauri::command]
pub async fn service_codex_profile_repair_history(
    addr: Option<String>,
    codex_home: Option<String>,
) -> Result<serde_json::Value, String> {
    let params = serde_json::json!({ "codexHome": codex_home });
    rpc_call_in_background("codexProfile/repairHistory", addr, Some(params)).await
}

/// 函数 `service_codex_profile_prune_history_backups`
///
/// 作者: gaohongshun
///
/// 时间: 2026-04-02
///
/// # 参数
/// - addr: 参数 addr
/// - codex_home: 参数 codex_home
///
/// # 返回
/// 返回函数执行结果
#[tauri::command]
pub async fn service_codex_profile_prune_history_backups(
    addr: Option<String>,
    codex_home: Option<String>,
) -> Result<serde_json::Value, String> {
    let params = serde_json::json!({ "codexHome": codex_home });
    rpc_call_in_background("codexProfile/pruneHistoryBackups", addr, Some(params)).await
}
