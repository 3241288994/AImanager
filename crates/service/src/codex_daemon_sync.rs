//! auth.json and a long-lived Codex app server have separate authentication state.
//! Never restart a daemon with active or unverified threads, and never inject short-lived
//! externally managed tokens (which would also require owning their refresh).
use std::path::Path;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum Readiness {
    Ready,
    Busy,
    Unknown,
}

pub(crate) fn identity_matches(profile: &Path, expected_email: &str) -> bool {
    let socket = profile.join("app-server-control/app-server-control.sock");
    if std::fs::symlink_metadata(&socket).is_err_and(|e| e.kind() == std::io::ErrorKind::NotFound) { return true; }
    #[cfg(unix)]
    {
        let profile=profile.to_path_buf(); let email=expected_email.to_owned();
        return std::thread::spawn(move || {
            let Ok(rt)=tokio::runtime::Builder::new_current_thread().enable_all().build() else { return false; };
            rt.block_on(async { match tokio::time::timeout(std::time::Duration::from_secs(5),probe(&profile, false)).await {
                Ok(Ok(s)) => s.account.get("type").and_then(serde_json::Value::as_str)==Some("chatgpt") && s.account.get("email").and_then(serde_json::Value::as_str).is_some_and(|s| s.eq_ignore_ascii_case(&email)),
                _=>false,
            } })
        }).join().unwrap_or(false);
    }
    #[cfg(not(unix))]
    false
}

/// Loaded-but-idle threads do not block switching. Active/unknown states do.
pub(crate) fn before_profile_write(profile: &Path) -> Readiness {
    let socket = profile.join("app-server-control/app-server-control.sock");
    match std::fs::symlink_metadata(&socket) {
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Readiness::Ready,
        Err(_) => return Readiness::Unknown,
        Ok(_) => {}
    }
    #[cfg(unix)]
    {
        let profile = profile.to_path_buf();
        std::thread::spawn(move || {
            let Ok(runtime) = tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .build()
            else {
                return Readiness::Unknown;
            };
            match runtime.block_on(async {
                tokio::time::timeout(std::time::Duration::from_secs(5), probe(&profile, true)).await
            }) {
                Ok(Ok(state)) => activity_readiness(&state.loaded),
                _ => Readiness::Unknown,
            }
        })
        .join()
        .unwrap_or(Readiness::Unknown)
    }
    #[cfg(not(unix))]
    Readiness::Unknown
}

pub(crate) fn after_profile_write(profile: &Path, expected_email: Option<&str>) -> Option<String> {
    #[cfg(unix)]
    {
        let socket = profile.join("app-server-control/app-server-control.sock");
        if std::fs::symlink_metadata(&socket).is_err_and(|e| e.kind() == std::io::ErrorKind::NotFound) {
            return None;
        }
        let profile = profile.to_path_buf();
        let email = expected_email.map(str::to_string);
        // RPC may be dispatched from an existing Tokio runtime.
        return std::thread::spawn(move || synchronize(&profile, email.as_deref())).join()
            .unwrap_or_else(|_| Some("Codex credentials were saved, but the background login check failed. Restart Codex after active tasks finish.".into()));
    }
    #[cfg(not(unix))]
    None
}

#[cfg(unix)]
fn synchronize(profile: &Path, expected_email: Option<&str>) -> Option<String> {
    use std::{
        process::{Command, Stdio},
        time::{Duration, Instant},
    };
    let failure = "Codex credentials were saved, but background activation could not be verified. Check the server proxy and run `codex app-server daemon restart` after active tasks finish.";
    let runtime = match tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
    {
        Ok(runtime) => runtime,
        Err(_) => return Some(failure.into()),
    };
    let probe = || {
        runtime.block_on(async {
            tokio::time::timeout(Duration::from_secs(5), probe(profile, true))
                .await
                .map_err(|_| ())?
        })
    };
    let before = match probe() {
        Ok(value) => value,
        Err(_) => return Some(failure.into()),
    };
    if !safe_to_restart(&before.loaded) {
        return Some("Codex credentials were saved. The background server has active or unverified tasks; they were not interrupted. Activation will need verification after those tasks become idle.".into());
    }
    let executable = profile.join("packages/app-server-daemon/current/bin/codex");
    if !executable.is_file() {
        return Some(failure.into());
    }
    // Recheck immediately before invoking the official lifecycle command.
    if !probe().is_ok_and(|state| safe_to_restart(&state.loaded)) {
        return Some(failure.into());
    }
    let mut child = match Command::new(executable)
        .args(["app-server", "daemon", "restart"])
        .env("CODEX_HOME", profile)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
    {
        Ok(child) => child,
        Err(_) => return Some(failure.into()),
    };
    let deadline = Instant::now() + Duration::from_secs(10);
    loop {
        match child.try_wait() {
            Ok(Some(status)) if status.success() => break,
            Ok(Some(_)) | Err(_) => return Some(failure.into()),
            Ok(None) if Instant::now() < deadline => std::thread::sleep(Duration::from_millis(100)),
            _ => {
                let _ = child.kill();
                let _ = child.wait();
                return Some(failure.into());
            }
        }
    }
    // Lifecycle success means the process started, not that authentication is ready.
    let deadline = Instant::now() + Duration::from_secs(5);
    loop {
        let verified = runtime.block_on(async {
            tokio::time::timeout(deadline.saturating_duration_since(Instant::now()), probe_identity(profile)).await
                .ok().and_then(Result::ok).is_some_and(|account| account_matches(&account, expected_email))
        });
        if verified { return None; }
        if Instant::now() >= deadline { return Some(failure.into()); }
        std::thread::sleep(Duration::from_millis(250));
    }
}

#[cfg(unix)]
async fn probe_identity(profile: &Path) -> Result<serde_json::Value, ()> {
    probe(profile, false).await.map(|snapshot| snapshot.account)
}

fn account_matches(account: &serde_json::Value, expected: Option<&str>) -> bool {
    account.get("type").and_then(serde_json::Value::as_str) == Some("chatgpt")
        && expected.filter(|email| !email.is_empty()).is_some_and(|email| {
            account.get("email").and_then(serde_json::Value::as_str)
                .is_some_and(|actual| actual.eq_ignore_ascii_case(email))
        })
}

#[cfg(any(unix, test))]
fn safe_to_restart(loaded: &serde_json::Value) -> bool {
    activity_readiness(loaded) == Readiness::Ready
}

#[cfg(any(unix, test))]
fn activity_readiness(loaded: &serde_json::Value) -> Readiness {
    let Some(threads) = loaded.get("data").and_then(serde_json::Value::as_array) else { return Readiness::Unknown; };
    if !loaded.get("nextCursor").is_some_and(serde_json::Value::is_null) { return Readiness::Unknown; }
    let mut result = Readiness::Ready;
    for status in threads {
        match status.get("type").and_then(serde_json::Value::as_str) {
            Some("idle" | "notLoaded") => {},
            // Includes waitingOnApproval and waitingOnUserInput, not just generation.
            Some("active") => return Readiness::Busy,
            _ => result = Readiness::Unknown,
        }
    }
    result
}

#[cfg(unix)]
struct Snapshot {
    account: serde_json::Value,
    loaded: serde_json::Value,
}

#[cfg(unix)]
async fn probe(profile: &Path, check_activity: bool) -> Result<Snapshot, ()> {
    use futures_util::{SinkExt, StreamExt};
    use serde_json::{json, Value};
    use tokio::net::UnixStream;
    use tokio_tungstenite::{client_async, tungstenite::Message, WebSocketStream};
    async fn call(
        ws: &mut WebSocketStream<UnixStream>,
        id: u64,
        method: &str,
        params: Value,
    ) -> Result<Value, ()> {
        ws.send(Message::Text(
            json!({"id": id, "method": method, "params": params})
                .to_string()
                .into(),
        ))
        .await
        .map_err(|_| ())?;
        // Bound unsolicited notifications as well as wall time. Never log them.
        for _ in 0..64 {
            let message = ws.next().await.ok_or(())?.map_err(|_| ())?;
            if let Message::Text(text) = message {
                let value: Value = serde_json::from_str(&text).map_err(|_| ())?;
                if value.get("id").and_then(Value::as_u64) == Some(id) {
                    return value.get("result").cloned().ok_or(());
                }
            }
        }
        Err(())
    }
    let stream = UnixStream::connect(profile.join("app-server-control/app-server-control.sock"))
        .await
        .map_err(|_| ())?;
    let (mut ws, _) = client_async("ws://localhost/", stream)
        .await
        .map_err(|_| ())?;
    call(&mut ws, 1, "initialize", json!({"clientInfo": {"name": "aimanager-account-sync", "version": "1"}, "capabilities": {}})).await?;
    ws.send(Message::Text(
        json!({"method": "initialized"}).to_string().into(),
    ))
    .await
    .map_err(|_| ())?;
    let mut loaded = json!({"data":[],"nextCursor":null});
    if check_activity {
        let ids = call(&mut ws, 2, "thread/loaded/list", json!({"limit":128})).await?;
        let data = ids.get("data").and_then(Value::as_array).ok_or(())?;
        if data.len()>128 || !ids.get("nextCursor").is_some_and(Value::is_null) { return Err(()); }
        let mut states = Vec::with_capacity(data.len());
        for (index,id) in data.iter().enumerate() {
            let id = id.as_str().filter(|id| !id.is_empty()).ok_or(())?;
            let thread = call(&mut ws, index as u64+3,"thread/read",json!({"threadId":id,"includeTurns":false})).await?;
            let thread = thread.get("thread").ok_or(())?;
            if thread.get("id").and_then(Value::as_str)!=Some(id) { return Err(()); }
            states.push(thread.get("status").cloned().ok_or(())?);
        }
        // A thread loaded during the scan must be checked on the next attempt.
        let after = call(&mut ws, 200,"thread/loaded/list",json!({"limit":128})).await?;
        if after != ids { return Err(()); }
        loaded = json!({"data":states,"nextCursor":null});
    }
    let account = call(&mut ws, 201, "account/read", json!({"refreshToken": false}))
        .await?
        .get("account")
        .cloned()
        .unwrap_or(Value::Null);
    let _ = ws.close(None).await;
    Ok(Snapshot { account, loaded })
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    #[test]
    fn idle_loaded_threads_allow_switching_but_active_or_unknown_do_not() {
        assert!(safe_to_restart(&json!({"data": [], "nextCursor": null})));
        assert!(safe_to_restart(&json!({"data":[{"type":"idle"},{"type":"notLoaded"}],"nextCursor":null})));
        assert_eq!(activity_readiness(&json!({"data":[{"type":"active","activeFlags":["waitingOnApproval"]}],"nextCursor":null})),Readiness::Busy);
        for value in [
            json!({}),
            json!({"data": []}),
            json!({"data": ["thread"], "nextCursor": null}),
            json!({"data": [], "nextCursor": "more"}),
            json!({"data": null, "nextCursor": null}),
            json!({"data":[{"type":"systemError"}],"nextCursor":null}),
            json!({"data":[{"type":"futureStatus"}],"nextCursor":null}),
        ] {
            assert!(!safe_to_restart(&value));
        }
    }
    #[test]
    fn does_not_start_a_daemon_for_profiles_without_one() {
        assert!(after_profile_write(Path::new("/nonexistent-aimanager-profile"), None).is_none());
    }
}
