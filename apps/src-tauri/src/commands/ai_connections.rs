use crate::commands::shared::rpc_call_in_background;

#[tauri::command]
pub async fn service_ai_accounts_action(
    addr: Option<String>,
    params: serde_json::Value,
) -> Result<serde_json::Value, String> {
    rpc_call_in_background("aiAccounts/action", addr, Some(params)).await
}

#[tauri::command]
pub async fn service_ai_connections_list(
    addr: Option<String>,
) -> Result<serde_json::Value, String> {
    rpc_call_in_background("aiConnections/list", addr, None).await
}
#[tauri::command]
pub async fn service_ai_connections_save(
    addr: Option<String>,
    connection: serde_json::Value,
) -> Result<serde_json::Value, String> {
    rpc_call_in_background("aiConnections/save", addr, Some(connection)).await
}
#[tauri::command]
pub async fn service_ai_connections_delete(
    addr: Option<String>,
    id: String,
) -> Result<serde_json::Value, String> {
    rpc_call_in_background(
        "aiConnections/delete",
        addr,
        Some(serde_json::json!({"id":id})),
    )
    .await
}
#[tauri::command]
pub async fn service_ai_connections_probe(
    addr: Option<String>,
    id: String,
) -> Result<serde_json::Value, String> {
    rpc_call_in_background(
        "aiConnections/probe",
        addr,
        Some(serde_json::json!({"id":id})),
    )
    .await
}

#[tauri::command]
pub async fn service_ai_connections_quota(addr: Option<String>, id: String) -> Result<serde_json::Value, String> {
    rpc_call_in_background("aiConnections/quota", addr, Some(serde_json::json!({"id":id}))).await
}
