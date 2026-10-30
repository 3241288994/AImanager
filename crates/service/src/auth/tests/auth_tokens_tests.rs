use super::next_account_sort;
use crate::account_identity::{build_account_storage_id, pick_existing_account_id_by_identity};
use crate::auth_tokens::{
    build_api_key_exchange_request, build_exchange_code_request, ensure_workspace_allowed,
    format_api_key_exchange_status_error, format_token_endpoint_status_error,
    issuer_uses_loopback_host, parse_token_endpoint_error,
};
use codexmanager_core::auth::parse_id_token_claims;
use codexmanager_core::storage::{now_ts, Account, Storage};
use reqwest::header::{HeaderMap, HeaderValue};
use reqwest::Client;

#[test]
fn device_pending_json_is_not_confused_with_a_verification_page() {
    let mut headers = HeaderMap::new();
    assert!(!super::device_verification_page(&headers));
    headers.insert("content-type", HeaderValue::from_static("application/json"));
    assert!(!super::device_verification_page(&headers));
    headers.insert("cf-ray", HeaderValue::from_static("ordinary-request"));
    assert!(!super::device_verification_page(&headers));
    headers.insert("cf-mitigated", HeaderValue::from_static("challenge"));
    assert!(super::device_verification_page(&headers));
    headers.remove("cf-mitigated");
    headers.insert("content-type", HeaderValue::from_static("text/html; charset=UTF-8"));
    assert!(super::device_verification_page(&headers));
}

#[test]
fn device_poll_stops_on_cloudflare_html_instead_of_waiting_fifteen_minutes() {
    let server = tiny_http::Server::http("127.0.0.1:0").unwrap();
    let issuer = format!("http://{}", server.server_addr());
    let responder = std::thread::spawn(move || {
        let request = server.recv_timeout(std::time::Duration::from_secs(5)).unwrap().unwrap();
        request.respond(tiny_http::Response::from_string("<html><title>Just a moment...</title></html>")
            .with_status_code(403)
            .with_header(tiny_http::Header::from_bytes("Content-Type", "text/html").unwrap())).unwrap();
    });
    let result = super::run_auth_future(super::poll_device_auth_token_async(&issuer, "synthetic-device", "TEST-CODE", 5));
    responder.join().unwrap();
    assert!(matches!(result, Err(ref error) if error == super::DEVICE_VERIFICATION_REQUIRED));
}

#[test]
fn device_poll_keeps_json_pending_responses_then_accepts_authorization() {
    let server = tiny_http::Server::http("127.0.0.1:0").unwrap();
    let issuer = format!("http://{}", server.server_addr());
    let responder = std::thread::spawn(move || {
        for status in [403, 404, 200] {
            let request = server.recv_timeout(std::time::Duration::from_secs(5)).unwrap().unwrap();
            let body = if status == 200 { r#"{"authorization_code":"synthetic-code","code_challenge":"test","code_verifier":"synthetic-verifier"}"# } else { r#"{"status":"pending"}"# };
            request.respond(tiny_http::Response::from_string(body).with_status_code(status)
                .with_header(tiny_http::Header::from_bytes("Content-Type", "application/json").unwrap())).unwrap();
        }
    });
    let result = super::run_auth_future(super::poll_device_auth_token_async(&issuer, "synthetic-device", "TEST-CODE", 1)).unwrap();
    responder.join().unwrap();
    assert_eq!(result.authorization_code, "synthetic-code");
}

/// 函数 `build_account`
///
/// 作者: gaohongshun
///
/// 时间: 2026-04-02
///
/// # 参数
/// - id: 参数 id
/// - chatgpt_account_id: 参数 chatgpt_account_id
/// - workspace_id: 参数 workspace_id
///
/// # 返回
/// 返回函数执行结果
fn build_account(
    id: &str,
    chatgpt_account_id: Option<&str>,
    workspace_id: Option<&str>,
) -> Account {
    let now = now_ts();
    Account {
        id: id.to_string(),
        label: id.to_string(),
        issuer: "https://auth.openai.com".to_string(),
        chatgpt_account_id: chatgpt_account_id.map(|v| v.to_string()),
        workspace_id: workspace_id.map(|v| v.to_string()),
        group_name: None,
        sort: 0,
        status: "active".to_string(),
        created_at: now,
        updated_at: now,
    }
}

/// 函数 `pick_existing_account_requires_exact_scope_when_workspace_present`
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
#[test]
fn pick_existing_account_requires_exact_scope_when_workspace_present() {
    let storage = Storage::open_in_memory().expect("open in memory");
    storage.init().expect("init");
    storage
        .insert_account(&build_account("acc-ws-a", Some("cgpt-1"), Some("ws-a")))
        .expect("insert ws-a");

    let found = pick_existing_account_id_by_identity(
        storage.list_accounts().expect("list accounts").iter(),
        Some("cgpt-1"),
        Some("ws-b"),
        Some("sub-fallback"),
        None,
    );

    assert_eq!(found, None);
}

/// 函数 `pick_existing_account_matches_exact_workspace_scope`
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
#[test]
fn pick_existing_account_matches_exact_workspace_scope() {
    let storage = Storage::open_in_memory().expect("open in memory");
    storage.init().expect("init");
    storage
        .insert_account(&build_account("acc-ws-a", Some("cgpt-1"), Some("ws-a")))
        .expect("insert ws-a");
    storage
        .insert_account(&build_account("acc-ws-b", Some("cgpt-1"), Some("ws-b")))
        .expect("insert ws-b");

    let found = pick_existing_account_id_by_identity(
        storage.list_accounts().expect("list accounts").iter(),
        Some("cgpt-1"),
        Some("ws-b"),
        Some("sub-fallback"),
        None,
    );

    assert_eq!(found.as_deref(), Some("acc-ws-b"));
}

/// 函数 `build_account_storage_id_keeps_login_scope_shape`
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
#[test]
fn build_account_storage_id_keeps_login_scope_shape() {
    let account_id = build_account_storage_id("sub-1", Some("cgpt-1"), Some("ws-a"), None);
    assert_eq!(account_id, "sub-1::cgpt=cgpt-1|ws=ws-a");
}

#[test]
fn oauth_workspace_fallback_reuses_resolved_same_subject_identity() {
    let account = build_account("sub::cgpt=cgpt-1|ws=org", Some("cgpt-1"), Some("org"));
    assert_eq!(pick_existing_account_id_by_identity([&account], Some("cgpt-1"), Some("cgpt-1"), Some("sub"), None), Some(account.id.clone()));
    assert_eq!(pick_existing_account_id_by_identity([&account], Some("cgpt-1"), Some("cgpt-1"), Some("other-sub"), None), None);
    let second = build_account("sub::cgpt=cgpt-1|ws=other", Some("cgpt-1"), Some("other"));
    assert_eq!(pick_existing_account_id_by_identity([&account, &second], Some("cgpt-1"), Some("cgpt-1"), Some("sub"), None), None);
}

#[test]
fn exact_duplicate_prefers_active_account() {
    let mut old = build_account("sub::cgpt=cgpt-1|ws=org", Some("cgpt-1"), Some("org"));
    old.status = "unavailable".into();
    let new = build_account("sub::cgpt=cgpt-1", Some("cgpt-1"), Some("org"));
    assert_eq!(pick_existing_account_id_by_identity([&old, &new], Some("cgpt-1"), Some("org"), Some("sub"), None), Some(new.id));
}

/// 函数 `next_account_sort_uses_step_five`
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
#[test]
fn next_account_sort_uses_step_five() {
    let storage = Storage::open_in_memory().expect("open in memory");
    storage.init().expect("init");
    storage
        .insert_account(&build_account("acc-1", Some("cgpt-1"), Some("ws-1")))
        .expect("insert account 1");
    storage
        .update_account_sort("acc-1", 2)
        .expect("update sort 1");
    storage
        .insert_account(&build_account("acc-2", Some("cgpt-2"), Some("ws-2")))
        .expect("insert account 2");
    storage
        .update_account_sort("acc-2", 7)
        .expect("update sort 2");

    assert_eq!(next_account_sort(&storage), 12);
}

/// 函数 `jwt_with_claims`
///
/// 作者: gaohongshun
///
/// 时间: 2026-04-02
///
/// # 参数
/// - payload: 参数 payload
///
/// # 返回
/// 返回函数执行结果
fn jwt_with_claims(payload: &str) -> String {
    format!("eyJhbGciOiJIUzI1NiJ9.{payload}.sig")
}

/// 函数 `ensure_workspace_allowed_accepts_matching_auth_chatgpt_account_id`
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
#[test]
fn ensure_workspace_allowed_accepts_matching_auth_chatgpt_account_id() {
    let token = jwt_with_claims(
        "eyJzdWIiOiJ1c2VyLTEiLCJodHRwczovL2FwaS5vcGVuYWkuY29tL2F1dGgiOnsiY2hhdGdwdF9hY2NvdW50X2lkIjoib3JnX2FiYyJ9fQ",
    );
    let claims = parse_id_token_claims(&token).expect("claims");

    let result = ensure_workspace_allowed(Some("org_abc"), &claims, &token, &token);

    assert!(result.is_ok(), "workspace should match: {:?}", result);
}

/// 函数 `ensure_workspace_allowed_rejects_mismatched_workspace`
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
#[test]
fn ensure_workspace_allowed_rejects_mismatched_workspace() {
    let token = jwt_with_claims("eyJzdWIiOiJ1c2VyLTEiLCJ3b3Jrc3BhY2VfaWQiOiJvcmdfYWJjIn0");
    let claims = parse_id_token_claims(&token).expect("claims");

    let result = ensure_workspace_allowed(Some("org_other"), &claims, &token, &token);

    assert_eq!(
        result.expect_err("should reject mismatch"),
        "Login is restricted to workspace id org_other."
    );
}

/// 函数 `ensure_workspace_allowed_accepts_composite_scope_values_after_normalization`
///
/// 作者: gaohongshun
///
/// 时间: 2026-04-17
///
/// # 参数
/// 无
///
/// # 返回
/// 无
#[test]
fn ensure_workspace_allowed_accepts_composite_scope_values_after_normalization() {
    let token = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyLTEiLCJ3b3Jrc3BhY2VfaWQiOiJnb29nbGUtb2F1dGgyfDEwNTY3MTMwNzY2NTg0MTQxOTc0ODo6Y2dwdD1lZDA4ZDU2YS1jMDM4LTQzMjItYjMyNS01M2Y1MDRjMGM4OGN8d3M9b3JnLUFQNnlwY01pODRUaGZ1ZWxpNkVVM0I0bSIsImh0dHBzOi8vYXBpLm9wZW5haS5jb20vYXV0aCI6eyJjaGF0Z3B0X2FjY291bnRfaWQiOiJnb29nbGUtb2F1dGgyfDEwNTY3MTMwNzY2NTg0MTQxOTc0ODo6Y2dwdD1lZDA4ZDU2YS1jMDM4LTQzMjItYjMyNS01M2Y1MDRjMGM4OGN8d3M9b3JnLUFQNnlwY01pODRUaGZ1ZWxpNkVVM0I0bSJ9fQ.sig".to_string();
    let claims = parse_id_token_claims(&token).expect("claims");

    let result = ensure_workspace_allowed(
        Some("org-AP6ypcMi84Thfueli6EU3B4m"),
        &claims,
        &token,
        &token,
    );

    assert!(result.is_ok(), "workspace should match after normalization");
}

/// 函数 `parse_token_endpoint_error_prefers_error_description`
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
#[test]
fn parse_token_endpoint_error_prefers_error_description() {
    let detail = parse_token_endpoint_error(
        r#"{"error":"invalid_grant","error_description":"refresh token expired"}"#,
    );

    assert_eq!(detail.to_string(), "refresh token expired");
}

/// 函数 `parse_token_endpoint_error_reads_nested_error_message_and_code`
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
#[test]
fn parse_token_endpoint_error_reads_nested_error_message_and_code() {
    let detail = parse_token_endpoint_error(
        r#"{"error":{"code":"proxy_auth_required","message":"proxy authentication required"}}"#,
    );

    assert_eq!(detail.to_string(), "proxy authentication required");
}

/// 函数 `parse_token_endpoint_error_preserves_plain_text_for_display`
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
#[test]
fn parse_token_endpoint_error_preserves_plain_text_for_display() {
    let detail = parse_token_endpoint_error("service unavailable");

    assert_eq!(detail.to_string(), "service unavailable");
}

/// 函数 `parse_token_endpoint_error_summarizes_challenge_html`
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
#[test]
fn parse_token_endpoint_error_summarizes_challenge_html() {
    let detail =
        parse_token_endpoint_error("<html><title>Just a moment...</title><body>cf</body></html>");

    assert_eq!(
        detail.to_string(),
        "Cloudflare 安全验证页（title=Just a moment...）"
    );
}

/// 函数 `parse_token_endpoint_error_summarizes_blocked_cloudflare_html`
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
#[test]
fn parse_token_endpoint_error_summarizes_blocked_cloudflare_html() {
    let detail = parse_token_endpoint_error(
        "<html><body>Cloudflare error: Sorry, you have been blocked</body></html>",
    );

    assert_eq!(
        detail.to_string(),
        "Access blocked by Cloudflare. This usually happens when connecting from a restricted region"
    );
}

/// 函数 `parse_token_endpoint_error_summarizes_generic_html`
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
#[test]
fn parse_token_endpoint_error_summarizes_generic_html() {
    let detail = parse_token_endpoint_error("<html><title>502 Bad Gateway</title></html>");

    assert_eq!(
        detail.to_string(),
        "上游返回 HTML 错误页（title=502 Bad Gateway）"
    );
}

/// 函数 `format_token_endpoint_status_error_appends_debug_headers`
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
#[test]
fn format_token_endpoint_status_error_appends_debug_headers() {
    let mut headers = HeaderMap::new();
    headers.insert(
        "x-oai-request-id",
        HeaderValue::from_static("req_token_123"),
    );
    headers.insert("cf-ray", HeaderValue::from_static("ray_token_123"));
    headers.insert(
        "x-openai-authorization-error",
        HeaderValue::from_static("expired_session"),
    );
    headers.insert(
        "x-error-json",
        HeaderValue::from_static("eyJlcnJvciI6eyJjb2RlIjoidG9rZW5fZXhwaXJlZCJ9fQ=="),
    );

    let message = format_token_endpoint_status_error(
        reqwest::StatusCode::FORBIDDEN,
        &headers,
        "<html><title>Just a moment...</title></html>",
    );

    assert!(message.contains("token endpoint returned status 403 Forbidden"));
    assert!(message.contains("Cloudflare 安全验证页（title=Just a moment...）"));
    assert!(message.contains("request_id=req_token_123"));
    assert!(message.contains("cf_ray=ray_token_123"));
    assert!(message.contains("auth_error=expired_session"));
    assert!(message.contains("identity_error_code=token_expired"));
    assert!(message.contains("kind=cloudflare_challenge"));
}

/// 函数 `format_token_endpoint_status_error_marks_cloudflare_blocked_kind`
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
#[test]
fn format_token_endpoint_status_error_marks_cloudflare_blocked_kind() {
    let mut headers = HeaderMap::new();
    headers.insert(
        "x-request-id",
        HeaderValue::from_static("req_token_blocked"),
    );
    headers.insert("cf-ray", HeaderValue::from_static("ray_token_blocked"));

    let message = format_token_endpoint_status_error(
        reqwest::StatusCode::FORBIDDEN,
        &headers,
        "<html><body>Cloudflare error: Sorry, you have been blocked</body></html>",
    );

    assert!(message.contains("token endpoint returned status 403 Forbidden"));
    assert!(message.contains(
        "Access blocked by Cloudflare. This usually happens when connecting from a restricted region"
    ));
    assert!(message.contains("request_id=req_token_blocked"));
    assert!(message.contains("cf_ray=ray_token_blocked"));
    assert!(message.contains("kind=cloudflare_blocked"));
}

/// 函数 `format_api_key_exchange_status_error_appends_debug_headers`
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
#[test]
fn format_api_key_exchange_status_error_appends_debug_headers() {
    let mut headers = HeaderMap::new();
    headers.insert("x-request-id", HeaderValue::from_static("req_api_key_123"));
    headers.insert("cf-ray", HeaderValue::from_static("ray_api_key_123"));
    headers.insert(
        "x-error-json",
        HeaderValue::from_static("eyJlcnJvciI6eyJjb2RlIjoicHJveHlfYXV0aF9yZXF1aXJlZCJ9fQ=="),
    );

    let message = format_api_key_exchange_status_error(
        reqwest::StatusCode::BAD_GATEWAY,
        &headers,
        "<html><title>502 Bad Gateway</title></html>",
    );

    assert!(message.contains("api key exchange failed with status 502 Bad Gateway"));
    assert!(message.contains("上游返回 HTML 错误页（title=502 Bad Gateway）"));
    assert!(message.contains("request_id=req_api_key_123"));
    assert!(message.contains("cf_ray=ray_api_key_123"));
    assert!(message.contains("identity_error_code=proxy_auth_required"));
    assert!(message.contains("kind=html"));
}

/// 函数 `format_token_endpoint_status_error_accepts_raw_error_json_header`
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
#[test]
fn format_token_endpoint_status_error_accepts_raw_error_json_header() {
    let mut headers = HeaderMap::new();
    headers.insert(
        "x-request-id",
        HeaderValue::from_static("req_token_raw_123"),
    );
    headers.insert(
        "x-error-json",
        HeaderValue::from_static("{\"identity_error_code\":\"org_membership_required\"}"),
    );

    let message = format_token_endpoint_status_error(
        reqwest::StatusCode::FORBIDDEN,
        &headers,
        "<html><title>Just a moment...</title></html>",
    );

    assert!(message.contains("request_id=req_token_raw_123"));
    assert!(message.contains("identity_error_code=org_membership_required"));
    assert!(message.contains("kind=cloudflare_challenge"));
}

/// 函数 `format_token_endpoint_status_error_uses_header_only_blocked_signal`
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
#[test]
fn format_token_endpoint_status_error_uses_header_only_blocked_signal() {
    let mut headers = HeaderMap::new();
    headers.insert(
        "x-openai-authorization-error",
        HeaderValue::from_static("unsupported_country_region_territory"),
    );
    headers.insert(
        "cf-ray",
        HeaderValue::from_static("ray_token_header_blocked"),
    );

    let message = format_token_endpoint_status_error(reqwest::StatusCode::FORBIDDEN, &headers, "");

    assert!(message.contains("token endpoint returned status 403 Forbidden"));
    assert!(message.contains(
        "Access blocked by Cloudflare. This usually happens when connecting from a restricted region"
    ));
    assert!(message.contains("auth_error=unsupported_country_region_territory"));
    assert!(message.contains("kind=cloudflare_blocked"));
}

/// 函数 `format_api_key_exchange_status_error_uses_identity_header_when_body_empty`
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
#[test]
fn format_api_key_exchange_status_error_uses_identity_header_when_body_empty() {
    let mut headers = HeaderMap::new();
    headers.insert(
        "x-error-json",
        HeaderValue::from_static("{\"identity_error_code\":\"org_membership_required\"}"),
    );

    let message =
        format_api_key_exchange_status_error(reqwest::StatusCode::FORBIDDEN, &headers, "");

    assert!(message.contains("api key exchange failed with status 403 Forbidden"));
    assert!(message.contains("identity error: org_membership_required"));
    assert!(message.contains("identity_error_code=org_membership_required"));
    assert!(message.contains("kind=identity_error"));
}

/// 函数 `format_token_endpoint_status_error_uses_cloudflare_edge_kind_when_only_cf_ray_exists`
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
#[test]
fn format_token_endpoint_status_error_uses_cloudflare_edge_kind_when_only_cf_ray_exists() {
    let mut headers = HeaderMap::new();
    headers.insert("cf-ray", HeaderValue::from_static("ray_token_only_cf"));

    let message =
        format_token_endpoint_status_error(reqwest::StatusCode::BAD_GATEWAY, &headers, "");

    assert!(message.contains("token endpoint returned status 502 Bad Gateway"));
    assert!(message.contains("cf_ray=ray_token_only_cf"));
    assert!(message.contains("kind=cloudflare_edge"));
}

/// 函数 `issuer_uses_loopback_host_accepts_local_test_issuers`
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
#[test]
fn issuer_uses_loopback_host_accepts_local_test_issuers() {
    assert!(issuer_uses_loopback_host("http://127.0.0.1:1455"));
    assert!(issuer_uses_loopback_host("http://localhost:1455"));
}

/// 函数 `issuer_uses_loopback_host_rejects_remote_issuers`
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
#[test]
fn issuer_uses_loopback_host_rejects_remote_issuers() {
    assert!(!issuer_uses_loopback_host("https://auth.openai.com"));
}

/// 函数 `exchange_code_for_tokens_matches_official_login_server_headers`
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
#[test]
fn exchange_code_for_tokens_matches_official_login_server_headers() {
    let client = Client::builder().no_proxy().build().expect("build client");
    let request = build_exchange_code_request(
        &client,
        "http://127.0.0.1:1455",
        "client-test",
        "http://localhost:1455/auth/callback",
        "verifier-test",
        "code-test",
    )
    .expect("build exchange request");

    let find = |name: &str| {
        request
            .headers()
            .get(name)
            .and_then(|value| value.to_str().ok())
    };
    let body = request
        .body()
        .and_then(|body| body.as_bytes())
        .map(|body| String::from_utf8_lossy(body).into_owned())
        .expect("request body");

    assert_eq!(request.url().path(), "/oauth/token");
    assert_eq!(
        find("Content-Type"),
        Some("application/x-www-form-urlencoded")
    );
    assert_eq!(find("Originator"), None);
    assert_eq!(find("x-openai-internal-codex-residency"), None);
    assert_eq!(find("User-Agent"), None);
    assert!(body.contains("grant_type=authorization_code"));
    assert!(body.contains("code=code-test"));
    assert!(body.contains("code_verifier=verifier-test"));
}

/// 函数 `obtain_api_key_matches_official_login_server_headers`
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
#[test]
fn obtain_api_key_matches_official_login_server_headers() {
    let client = Client::builder().no_proxy().build().expect("build client");
    let request = build_api_key_exchange_request(
        &client,
        "http://127.0.0.1:1455",
        "client-test",
        "id-token-test",
    )
    .expect("build api key exchange request");

    let find = |name: &str| {
        request
            .headers()
            .get(name)
            .and_then(|value| value.to_str().ok())
    };
    let body = request
        .body()
        .and_then(|body| body.as_bytes())
        .map(|body| String::from_utf8_lossy(body).into_owned())
        .expect("request body");

    assert_eq!(request.url().path(), "/oauth/token");
    assert_eq!(
        find("Content-Type"),
        Some("application/x-www-form-urlencoded")
    );
    assert_eq!(find("Originator"), None);
    assert_eq!(find("x-openai-internal-codex-residency"), None);
    assert_eq!(find("User-Agent"), None);
    assert!(body.contains("grant_type=urn%3Aietf%3Aparams%3Aoauth%3Agrant-type%3Atoken-exchange"));
    assert!(body.contains("requested_token=openai-api-key"));
}
