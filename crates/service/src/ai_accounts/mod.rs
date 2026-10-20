//! Administrator-only managed CLI profiles; native OAuth remains owned by each CLI.
use serde_json::Value;
use std::{
    io::{Read, Write},
    path::PathBuf,
    process::{Command, Stdio},
    time::{Duration, Instant},
};

const WORKER: &str = include_str!("worker.py");
const ACTIONS: &[&str] = &[
    "list",
    "sync",
    "connect",
    "create",
    "select",
    "login",
    "usage",
    "check",
    "session",
    "input",
    "cancel",
    "models",
    "analytics",
];

fn state_root() -> Result<PathBuf, String> {
    if let Some(path) = std::env::var_os("AIMANAGER_STATE_DIR") {
        let path = PathBuf::from(path);
        if !path.is_absolute() {
            return Err("AIMANAGER_STATE_DIR must be absolute".into());
        }
        return Ok(path);
    }
    std::env::var_os("HOME")
        .or_else(|| std::env::var_os("USERPROFILE"))
        .map(|home| PathBuf::from(home).join(".local/state/aimanager"))
        .ok_or_else(|| "Service home is unavailable".into())
}

fn install_worker(root: &std::path::Path) -> Result<PathBuf, String> {
    std::fs::create_dir_all(root).map_err(|_| "Cannot create private CLI state directory")?;
    if std::fs::symlink_metadata(root)
        .map_err(|_| "Cannot inspect CLI state")?
        .file_type()
        .is_symlink()
    {
        return Err("CLI state directory cannot be a symlink".into());
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(root, std::fs::Permissions::from_mode(0o700))
            .map_err(|_| "Cannot secure CLI state directory")?;
    }
    let script = root.join("worker.py");
    for (filename, content) in [
        ("usage_history.py", include_str!("usage_history.py")),
        ("worker.py", WORKER),
    ] {
        let script = root.join(filename);
        // Install an embedded, reviewed worker, never a user-supplied script path.
        if std::fs::read_to_string(&script).ok().as_deref() != Some(content) {
            let temporary = root.join(format!(
                ".worker-{}-{}.tmp",
                std::process::id(),
                rand::random::<u64>()
            ));
            let mut options = std::fs::OpenOptions::new();
            options.write(true).create_new(true);
            #[cfg(unix)]
            {
                use std::os::unix::fs::OpenOptionsExt;
                options.mode(0o700);
            }
            let mut file = options
                .open(&temporary)
                .map_err(|_| "Cannot install CLI worker")?;
            file.write_all(content.as_bytes())
                .map_err(|_| "Cannot write CLI worker")?;
            std::fs::rename(&temporary, &script).map_err(|_| "Cannot activate CLI worker")?;
        }
    }
    Ok(script)
}

pub(crate) fn action(params: Value) -> Result<Value, String> {
    #[cfg(windows)]
    {
        let _ = params;
        return Err(
            "Managed OAuth sessions currently require Linux or macOS and Python 3.8+".into(),
        );
    }
    #[cfg(not(windows))]
    {
        let name = params.get("action").and_then(Value::as_str).unwrap_or("");
        if !ACTIONS.contains(&name) {
            return Err("Unsupported CLI account action".into());
        }
        let input = serde_json::to_vec(&params).map_err(|_| "Invalid CLI account request")?;
        if input.len() > 16384 {
            return Err("CLI account request is too large".into());
        }
        let root = state_root()?;
        let script = install_worker(&root)?;
        let mut command = Command::new("python3");
        command
            .arg(&script)
            .arg("--root")
            .arg(&root)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .env_clear();
        for (key, value) in std::env::vars_os() {
            let key_text = key.to_string_lossy();
            if matches!(
                key_text.as_ref(),
                "PATH"
                    | "HOME"
                    | "USERPROFILE"
                    | "LANG"
                    | "LC_ALL"
                    | "HTTP_PROXY"
                    | "HTTPS_PROXY"
                    | "ALL_PROXY"
                    | "NO_PROXY"
                    | "http_proxy"
                    | "https_proxy"
                    | "all_proxy"
                    | "no_proxy"
                    | "SSL_CERT_FILE"
                    | "SSL_CERT_DIR"
                    | "NODE_EXTRA_CA_CERTS"
                    | "TMPDIR"
                    | "AIMANAGER_CLAUDE_BIN"
                    | "AIMANAGER_ANTIGRAVITY_BIN"
            ) {
                command.env(key, value);
            }
        }
        let mut child = command
            .spawn()
            .map_err(|_| "Cannot start CLI manager; Python 3.8+ is required on the service host")?;
        if let Some(mut stdin) = child.stdin.take() {
            if stdin.write_all(&input).is_err() {
                let _ = child.kill();
                let _ = child.wait();
                return Err("Cannot send private CLI operation".into());
            }
        }
        let stdout = child
            .stdout
            .take()
            .ok_or("CLI manager stdout is unavailable")?;
        let reader = std::thread::spawn(move || {
            let mut output = Vec::new();
            stdout
                .take(1048577)
                .read_to_end(&mut output)
                .map(|_| output)
        });
        let deadline = Instant::now() + Duration::from_secs(22);
        loop {
            if child
                .try_wait()
                .map_err(|_| "Cannot inspect CLI manager")?
                .is_some()
            {
                break;
            }
            if Instant::now() >= deadline {
                let _ = child.kill();
                let _ = child.wait();
                return Err(
                    "CLI manager timed out; check service-host CLI installation and network".into(),
                );
            }
            std::thread::sleep(Duration::from_millis(30));
        }
        let bytes = reader
            .join()
            .map_err(|_| "CLI response reader failed")?
            .map_err(|_| "Cannot read CLI response")?;
        if bytes.len() > 1048576 {
            return Err("CLI manager response exceeded 1 MiB".into());
        }
        let response: Value = serde_json::from_slice(&bytes)
            .map_err(|_| "CLI manager returned invalid data; Python 3.8+ is required")?;
        if let Some(error) = response.get("error").and_then(Value::as_str) {
            return Err(error.to_string());
        }
        response
            .get("result")
            .cloned()
            .ok_or_else(|| "CLI manager returned no result".into())
    }
}

#[cfg(test)]
mod tests {
    #[test]
    fn rejects_arbitrary_operations_before_starting_any_process() {
        assert!(
            super::action(serde_json::json!({"action":"shell", "command":"rm -rf /"})).is_err()
        );
    }
}
