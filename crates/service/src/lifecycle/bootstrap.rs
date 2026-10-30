pub mod portable {
    /// 函数 `bootstrap_current_process`
    ///
    /// 作者: gaohongshun
    ///
    /// 时间: 2026-04-02
    ///
    /// # 参数
    /// 无
    ///
    /// # 返回
    /// 无
    pub fn bootstrap_current_process() {
        crate::process_env::load_env_from_exe_dir();
        crate::process_env::ensure_default_db_path();
        let _ = crate::rpc_auth_token();
    }
}

/// 函数 `initialize_storage_if_needed`
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
pub fn initialize_storage_if_needed() -> Result<(), String> {
    crate::storage_helpers::initialize_storage()?;
    if let Some(storage) = crate::storage_helpers::open_storage() {
        crate::account::reconciliation::reconcile(&storage)?;
    }
    let _ = crate::auth::bootstrap_web_access_password_from_env()?;
    Ok(())
}
