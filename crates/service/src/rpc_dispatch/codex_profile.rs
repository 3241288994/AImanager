use codexmanager_core::rpc::types::{JsonRpcRequest, JsonRpcResponse};

pub(super) fn try_handle(req: &JsonRpcRequest) -> Option<JsonRpcResponse> {
    let result = match req.method.as_str() {
        "codexDevices/status" => super::value_or_error(crate::codex_devices::status()),
        "codexDevices/login" => super::value_or_error(crate::codex_devices::login(super::str_param(req,"deviceId"),super::str_param(req,"accountId"))),
        "codexDevices/heartbeat" => super::value_or_error(crate::codex_devices::heartbeat(req.params.as_ref().unwrap_or(&serde_json::Value::Null))),
        "codexProfile/cancelSwitch" => super::value_or_error(crate::codex_account_switch::cancel(super::str_param(req, "requestId"))),
        "codexProfile/get" => super::value_or_error(crate::codex_profile::get_status(
            super::str_param(req, "codexHome"),
        )),
        "codexProfile/setConfig" => super::value_or_error(crate::codex_profile::set_config(
            super::str_param(req, "codexHome"),
        )),
        "codexProfile/listCandidates" => {
            super::value_or_error(crate::codex_profile::list_candidates())
        }
        "codexProfile/applyDirectAccount" => {
            if super::bool_param(req,"syncDevices") == Some(true) {
                return Some(super::response(req, super::value_or_error(crate::codex_account_switch::request_scoped(super::str_param(req,"accountId"),super::str_param(req,"codexHome"),true))));
            }
            super::value_or_error(crate::codex_profile::apply_direct_account(
                super::str_param(req, "accountId"),
                super::str_param(req, "codexHome"),
            ))
        }
        "codexProfile/applyGateway" => super::value_or_error(crate::codex_profile::apply_gateway(
            super::str_param(req, "apiKeyId"),
            super::str_param(req, "codexHome"),
            super::str_param(req, "baseUrl"),
        )),
        "codexProfile/restore" => super::value_or_error(crate::codex_profile::restore(
            super::str_param(req, "codexHome"),
        )),
        "codexProfile/repairHistory" => super::value_or_error(
            crate::codex_profile::repair_history(super::str_param(req, "codexHome")),
        ),
        "codexProfile/pruneHistoryBackups" => super::value_or_error(
            crate::codex_profile::prune_history_backups(super::str_param(req, "codexHome")),
        ),
        _ => return None,
    };
    Some(super::response(req, result))
}
