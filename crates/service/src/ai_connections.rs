//! Administrator-only connection inventory. Credentials never enter RPC payloads.
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{
    io::Read,
    path::PathBuf,
    time::{Duration, Instant},
};

const SETTING: &str = "aimanager.connections.v1";
const MAX_BODY: u64 = 262144;

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct Connection {
    pub id: String,
    pub name: String,
    pub base_url: String,
    pub credential_source: String,
    pub enabled: bool,
}

fn home() -> Result<PathBuf, String> {
    std::env::var_os("HOME")
        .or_else(|| std::env::var_os("USERPROFILE"))
        .map(PathBuf::from)
        .ok_or_else(|| "Service home directory is unavailable".into())
}

fn defaults() -> Vec<Connection> {
    vec![Connection {
        id: "gemini-web".into(),
        name: "Gemini 网页账号池".into(),
        base_url: if cfg!(target_os = "macos") {
            "http://127.0.0.1:6969/v1"
        } else {
            "http://127.0.0.1:16969/v1"
        }
        .into(),
        credential_source: "gemini-web-client".into(),
        enabled: true,
    }]
}

fn validate(connection: &Connection) -> Result<url::Url, String> {
    if connection.id.is_empty()
        || connection.id.len() > 64
        || !connection
            .id
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_')
    {
        return Err("Connection ID must contain 1–64 letters, digits, - or _".into());
    }
    if connection.name.trim().is_empty() || connection.name.len() > 160 {
        return Err("Connection name is required (maximum 160 bytes)".into());
    }
    if !matches!(
        connection.credential_source.as_str(),
        "gemini-web-client" | "aimanager-env"
    ) {
        return Err("Unknown credential source".into());
    }
    let parsed = url::Url::parse(&connection.base_url).map_err(|_| "Invalid API URL")?;
    // No DNS resolution or redirects: do not send private credentials to arbitrary hosts.
    if !matches!(parsed.scheme(), "http" | "https")
        || !matches!(parsed.host_str(), Some("127.0.0.1" | "[::1]"))
        || !parsed.username().is_empty()
        || parsed.password().is_some()
        || parsed.query().is_some()
        || parsed.fragment().is_some()
        || parsed.path().trim_end_matches('/') != "/v1"
    {
        return Err(
            "Use a numeric loopback API URL ending in /v1, without credentials or query parameters"
                .into(),
        );
    }
    Ok(parsed)
}

pub(crate) fn list() -> Result<Vec<Connection>, String> {
    let Some(raw) = crate::app_settings::get_persisted_app_setting(SETTING) else {
        return Ok(defaults());
    };
    serde_json::from_str(&raw)
        .map_err(|_| "Saved AI connections are invalid; configuration was not overwritten".into())
}

pub(crate) fn save(connection: Connection) -> Result<Value, String> {
    validate(&connection)?;
    let mut items = list()?;
    if let Some(item) = items.iter_mut().find(|item| item.id == connection.id) {
        *item = connection;
    } else {
        if items.len() >= 32 {
            return Err("At most 32 connections are supported".into());
        }
        items.push(connection);
    }
    persist(&items)?;
    Ok(json!({"items": items}))
}

fn persist(items: &[Connection]) -> Result<(), String> {
    let raw = serde_json::to_string(items).map_err(|_| "Cannot serialize connections")?;
    crate::app_settings::save_persisted_app_setting(SETTING, Some(&raw))
}

pub(crate) fn delete(id: &str) -> Result<Value, String> {
    let mut items = list()?;
    items.retain(|item| item.id != id);
    persist(&items)?;
    Ok(json!({"items": items}))
}

fn parse_key(text: &str) -> Result<String, String> {
    for line in text.lines() {
        let line = line.trim().strip_prefix("export ").unwrap_or(line.trim());
        let Some((name, value)) = line.split_once('=') else {
            continue;
        };
        if name.trim() != "GEMINI_WEB_API_KEY" {
            continue;
        }
        let value = value.trim();
        let value = if value.len() >= 2
            && ((value.starts_with('"') && value.ends_with('"'))
                || (value.starts_with('\'') && value.ends_with('\'')))
        {
            &value[1..value.len() - 1]
        } else {
            value
        };
        if !value.is_empty() && !value.contains(['\r', '\n']) {
            return Ok(value.into());
        }
    }
    Err(
        "GEMINI_WEB_API_KEY is missing; configure the private client.env file on the service host"
            .into(),
    )
}

fn credential(source: &str) -> Result<String, String> {
    if source == "aimanager-env" {
        return std::env::var("AIMANAGER_UPSTREAM_API_KEY")
            .ok()
            .filter(|s| !s.trim().is_empty())
            .ok_or_else(|| {
                "AIMANAGER_UPSTREAM_API_KEY is not configured on the service host".into()
            });
    }
    let home = home()?;
    let path = if cfg!(target_os = "macos") {
        home.join(".local/share/gemini-web-pool/server-client/client.env")
    } else {
        home.join(".config/gemini-web-client/client.env")
    };
    let file = std::fs::File::open(&path)
        .map_err(|_| "Cannot open the private Gemini client.env on the service host")?;
    let metadata = file
        .metadata()
        .map_err(|_| "Cannot inspect credential file")?;
    if !metadata.is_file() || metadata.len() > 32768 {
        return Err("Credential file must be a regular file below 32 KiB".into());
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if metadata.permissions().mode() & 0o077 != 0 {
            return Err("Credential file permissions are too broad; set client.env to 0600".into());
        }
    }
    let mut text = String::new();
    file.take(32769)
        .read_to_string(&mut text)
        .map_err(|_| "Cannot read credential file as UTF-8")?;
    parse_key(&text)
}

fn get_json(client: &reqwest::blocking::Client, url: url::Url, key: &str) -> Result<Value, String> {
    let response = client.get(url).bearer_auth(key).send().map_err(|err| {
        if err.is_timeout() {
            "Request timed out; check the account pool and SSH tunnel".to_string()
        } else {
            "Connection failed; check the listener and SSH tunnel on the service host".to_string()
        }
    })?;
    let status = response.status();
    if !status.is_success() {
        return Err(format!("Upstream returned HTTP {}", status.as_u16()));
    }
    let mut body = Vec::new();
    response
        .take(MAX_BODY + 1)
        .read_to_end(&mut body)
        .map_err(|_| "Cannot read upstream response")?;
    if body.len() as u64 > MAX_BODY {
        return Err("Upstream response exceeded 256 KiB".into());
    }
    serde_json::from_slice(&body).map_err(|_| "Upstream returned invalid JSON".into())
}

pub(crate) fn probe(id: &str) -> Result<Value, String> {
    let connection = list()?
        .into_iter()
        .find(|item| item.id == id)
        .ok_or("Unknown connection")?;
    if !connection.enabled {
        return Err("Connection is disabled".into());
    }
    let base = validate(&connection)?;
    let key = credential(&connection.credential_source)?;
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(12))
        .connect_timeout(Duration::from_secs(3))
        .redirect(reqwest::redirect::Policy::none())
        .no_proxy()
        .build()
        .map_err(|_| "Cannot create probe client")?;
    let started = Instant::now();
    let models = get_json(
        &client,
        base.join("/v1/models").map_err(|_| "Invalid models URL")?,
        &key,
    )?;
    let data = models
        .get("data")
        .and_then(Value::as_array)
        .ok_or("Missing model data array")?;
    let ids: Vec<String> = data
        .iter()
        .take(256)
        .filter_map(|v| v.get("id")?.as_str())
        .filter(|v| v.len() <= 200 && !v.chars().any(char::is_control) && !v.contains(key.as_str()))
        .map(String::from)
        .collect();
    // Do not return raw health JSON: third-party pools may include cookies or tokens.
    let (health, summary, health_error) = if connection.credential_source == "gemini-web-client" {
        match get_json(
            &client,
            base.join("/health").map_err(|_| "Invalid health URL")?,
            &key,
        ) {
            Ok(value) => ("reachable", health_summary(&value), None),
            Err(error) => ("unavailable", Value::Null, Some(error)),
        }
    } else {
        ("not_checked", Value::Null, None)
    };
    Ok(
        json!({"id": id, "status": "reachable", "latencyMs": started.elapsed().as_millis(),
        "models": ids, "health": health, "healthSummary": summary, "healthError": health_error, "generationVerified": false,
        "note": "模型目录与健康端点检查不代表生成成功；未发送生成请求，不消耗模型额度。"}),
    )
}

fn health_summary(value: &Value) -> Value {
    let accounts = value.get("accounts").and_then(Value::as_array).map(|items| {
        items.iter().take(32).enumerate().map(|(index, item)| {
            let status = item.get("status").and_then(Value::as_str).unwrap_or("unknown");
            let status = match status {
                "ready" | "available" | "active" | "busy" | "cooldown" | "needs_login"
                | "login_required" | "offline" | "unavailable" | "error" | "recovering" => status,
                _ => "unknown",
            };
            json!({"index":index + 1, "status":status,
                "cooldownSeconds":item.get("cooldown_seconds").and_then(Value::as_u64).map(|n| n.min(86400))})
        }).collect::<Vec<_>>()
    });
    json!({"readyAccounts":value.get("ready_accounts").and_then(Value::as_u64).map(|n| n.min(10000)), "accounts":accounts})
}

fn installed(binary: &str) -> bool {
    if let Ok(home) = home() {
        let managed = home.join(".local/share/aimanager/bin").join(binary);
        if managed.is_file() {
            #[cfg(unix)]
            {
                use std::os::unix::fs::PermissionsExt;
                if managed
                    .metadata()
                    .map(|m| m.permissions().mode() & 0o111 != 0)
                    .unwrap_or(false)
                {
                    return true;
                }
            }
            #[cfg(not(unix))]
            {
                return true;
            }
        }
    }
    std::env::var_os("PATH")
        .map(|path| {
            std::env::split_paths(&path).any(|dir| {
                let path = dir.join(if cfg!(windows) {
                    format!("{binary}.exe")
                } else {
                    binary.into()
                });
                if !path.is_file() {
                    return false;
                }
                #[cfg(unix)]
                {
                    use std::os::unix::fs::PermissionsExt;
                    return path
                        .metadata()
                        .map(|m| m.permissions().mode() & 0o111 != 0)
                        .unwrap_or(false);
                }
                #[cfg(not(unix))]
                {
                    true
                }
            })
        })
        .unwrap_or(false)
}

pub(crate) fn overview() -> Result<Value, String> {
    Ok(
        json!({"items": list()?, "host": std::env::consts::OS, "cli": [
            {"id":"codex", "name":"Codex", "installed":installed("codex"), "command":"codex login", "authStatus":"not_checked"},
            {"id":"claude", "name":"Claude Code", "installed":installed("claude"), "command":"claude auth login", "authStatus":"not_checked"},
            {"id":"antigravity", "name":"Antigravity", "installed":installed("agy"), "command":"agy", "authStatus":"not_checked"}
        ]}),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rejects_non_loopback_and_embedded_secrets() {
        for url in [
            "https://evil.example/v1",
            "http://localhost/v1",
            "http://127.0.0.1/v1?key=x",
            "http://key@127.0.0.1/v1",
            "file:///v1",
            "http://127.0.0.1/admin",
        ] {
            let mut c = defaults().remove(0);
            c.base_url = url.into();
            assert!(validate(&c).is_err(), "{url}");
        }
    }
    #[test]
    fn accepts_loopback() {
        for url in ["http://127.0.0.1:16969/v1", "http://[::1]:6969/v1/"] {
            let mut c = defaults().remove(0);
            c.base_url = url.into();
            assert!(validate(&c).is_ok());
        }
    }
    #[test]
    fn env_is_parsed_not_executed() {
        assert_eq!(
            parse_key("OTHER=secret\nexport GEMINI_WEB_API_KEY='test-key'\n").unwrap(),
            "test-key"
        );
        assert!(parse_key("OTHER=secret").is_err());
        assert!(!parse_key("GEMINI_WEB_API_KEY=\n").is_ok());
    }
    #[test]
    fn payload_never_accepts_plaintext_credentials() {
        assert!(serde_json::from_value::<Connection>(json!({"id":"x","name":"x","baseUrl":"http://127.0.0.1/v1","credentialSource":"aimanager-env","enabled":true,"apiKey":"secret"})).is_err());
    }
    #[test]
    fn health_summary_drops_identifiers_cookies_and_unknown_status_text() {
        let value = health_summary(&json!({"cookie":"secret", "ready_accounts":1,
            "accounts":[{"id":"private-email", "token":"secret", "status":"ready", "cooldown_seconds":0},
            {"status":"secret-unexpected-value", "cooldown_seconds":999999}]}));
        let serialized = value.to_string();
        assert!(!serialized.contains("secret"));
        assert!(!serialized.contains("private-email"));
        assert_eq!(value["accounts"][1]["status"], "unknown");
        assert_eq!(value["accounts"][1]["cooldownSeconds"], 86400);
    }
    fn serve_once(status: &str, body: String, extra: &str) -> url::Url {
        use std::{net::TcpListener, thread};
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let response = format!(
            "HTTP/1.1 {status}\r\nContent-Length: {}\r\nConnection: close\r\n{extra}\r\n{body}",
            body.len()
        );
        thread::spawn(move || {
            use std::io::Write;
            let (mut stream, _) = listener.accept().unwrap();
            stream
                .set_read_timeout(Some(Duration::from_secs(2)))
                .unwrap();
            let mut request = [0; 8192];
            let _ = stream.read(&mut request);
            let _ = stream.write_all(response.as_bytes());
        });
        url::Url::parse(&format!("http://{address}/v1/models")).unwrap()
    }
    fn test_client() -> reqwest::blocking::Client {
        reqwest::blocking::Client::builder()
            .no_proxy()
            .redirect(reqwest::redirect::Policy::none())
            .timeout(Duration::from_secs(3))
            .build()
            .unwrap()
    }
    #[test]
    fn probe_reads_real_http_json() {
        let url = serve_once("200 OK", r#"{"data":[{"id":"model-alias"}]}"#.into(), "");
        let value = get_json(&test_client(), url, "dummy-test-key").unwrap();
        assert_eq!(value["data"][0]["id"], "model-alias");
    }
    #[test]
    fn probe_does_not_follow_redirects() {
        let url = serve_once(
            "302 Found",
            "".into(),
            "Location: http://127.0.0.1:1/secret\r\n",
        );
        assert_eq!(
            get_json(&test_client(), url, "dummy-test-key").unwrap_err(),
            "Upstream returned HTTP 302"
        );
    }
    #[test]
    fn probe_never_returns_error_body_secrets() {
        let url = serve_once("401 Unauthorized", "sensitive-upstream-body".into(), "");
        assert_eq!(
            get_json(&test_client(), url, "dummy-test-key").unwrap_err(),
            "Upstream returned HTTP 401"
        );
    }
    #[test]
    fn probe_bounds_response_size() {
        let url = serve_once("200 OK", "x".repeat(MAX_BODY as usize + 1), "");
        assert_eq!(
            get_json(&test_client(), url, "dummy-test-key").unwrap_err(),
            "Upstream response exceeded 256 KiB"
        );
    }
}
