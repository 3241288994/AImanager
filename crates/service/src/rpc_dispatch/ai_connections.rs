use codexmanager_core::rpc::types::{JsonRpcRequest, JsonRpcResponse};

pub(super) fn try_handle(req: &JsonRpcRequest) -> Option<JsonRpcResponse> {
    let result = match req.method.as_str() {
        "aiConnections/list" => crate::ai_connections::overview(),
        "aiConnections/save" => req
            .params
            .clone()
            .ok_or_else(|| "Missing connection".into())
            .and_then(|value| {
                serde_json::from_value(value).map_err(|_| "Invalid connection payload".to_string())
            })
            .and_then(crate::ai_connections::save),
        "aiConnections/delete" => {
            crate::ai_connections::delete(super::str_param(req, "id").unwrap_or(""))
        }
        "aiConnections/quota" => {
            crate::ai_connections::quota(super::str_param(req, "id").unwrap_or(""))
        }
        "aiConnections/probe" => {
            crate::ai_connections::probe(super::str_param(req, "id").unwrap_or(""))
        }
        _ => return None,
    };
    Some(super::response(req, super::value_or_error(result)))
}
