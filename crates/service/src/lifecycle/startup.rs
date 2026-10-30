use std::io;
use std::thread;

pub struct ServerHandle {
    pub addr: String,
    join: thread::JoinHandle<()>,
}

impl ServerHandle {
    /// 函数 `join`
    ///
    /// 作者: gaohongshun
    ///
    /// 时间: 2026-04-02
    ///
    /// # 参数
    /// - self: 参数 self
    ///
    /// # 返回
    /// 无
    pub fn join(self) {
        let _ = self.join.join();
    }
}

/// 函数 `start_one_shot_server`
///
/// 作者: gaohongshun
///
/// 时间: 2026-04-02
///
/// # 参数
/// 无
///
/// # 返回
/// 返回函数执行结果
pub fn start_one_shot_server() -> std::io::Result<ServerHandle> {
    crate::portable::bootstrap_current_process();
    if let Err(err) = crate::storage_helpers::initialize_storage() {
        log::warn!("storage startup init skipped: {}", err);
    }
    crate::sync_runtime_settings_from_storage();
    let server = tiny_http::Server::http("127.0.0.1:0")
        .map_err(|err| io::Error::new(io::ErrorKind::Other, err))?;
    let addr = server
        .server_addr()
        .to_ip()
        .map(|a| a.to_string())
        .ok_or_else(|| io::Error::new(io::ErrorKind::Other, "server addr missing"))?;
    let join = thread::spawn(move || {
        if let Some(request) = server.incoming_requests().next() {
            crate::http::backend_router::handle_backend_request(request);
        }
    });
    Ok(ServerHandle { addr, join })
}

/// 函数 `start_server`
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
pub fn start_server(addr: &str) -> std::io::Result<()> {
    crate::portable::bootstrap_current_process();
    if let Err(err) = crate::storage_helpers::initialize_storage() {
        log::warn!("storage startup init skipped: {}", err);
    }
    crate::sync_runtime_settings_from_storage();
    crate::usage_refresh::ensure_usage_polling();
    crate::usage_refresh::ensure_token_refresh_polling();
    // Start independently of any page/API visit so durable switches resume even
    // when the browser stays closed after a service restart.
    #[cfg(not(test))]
    crate::codex_account_switch::start_worker();
    crate::http::server::start_http(addr)
}
