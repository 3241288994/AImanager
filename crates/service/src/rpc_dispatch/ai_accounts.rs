use codexmanager_core::rpc::types::{JsonRpcRequest, JsonRpcResponse};
pub(super) fn try_handle(req: &JsonRpcRequest) -> Option<JsonRpcResponse> {
    if req.method != "aiAccounts/action" {
        return None;
    }
    Some(super::response(
        req,
        super::value_or_error(crate::ai_accounts::action(
            req.params.clone().unwrap_or_default(),
        )),
    ))
}
