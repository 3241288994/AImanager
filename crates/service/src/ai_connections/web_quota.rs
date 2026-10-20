use super::*;

fn finite(value: &Value) -> Option<f64> {
    value.as_f64().filter(|v| v.is_finite() && *v >= 0.0)
}

fn timestamp(value: &Value) -> Option<String> {
    if let Some(raw) = value.as_str() {
        return chrono::DateTime::parse_from_rfc3339(raw)
            .ok()
            .map(|v| v.to_rfc3339());
    }
    finite(value)
        .filter(|n| *n < 253402300799.0)
        .and_then(|n| {
            chrono::DateTime::from_timestamp(
                n.floor() as i64,
                ((n.fract() * 1e9) as u32).min(999999999),
            )
        })
        .map(|v| v.to_rfc3339())
}

fn window(value: &Value, label: &str) -> Value {
    // The pool's authoritative counter is usage_level (0..1). Missing is unknown.
    let remaining = finite(&value["usage_level"])
        .filter(|v| *v <= 1.0)
        .map(|v| ((1.0 - v) * 1000.0).round() / 10.0);
    json!({"label":label, "remainingPercent":remaining,
        "remainingCredits": finite(&value["remaining_credits"]).filter(|v| *v <= 1e15),
        "resetsAt": timestamp(&value["reset_at"])})
}

fn summary(value: &Value) -> Result<Value, String> {
    let items = value["accounts"]
        .as_array()
        .ok_or("Account pool did not return an accounts array")?;
    let basic = health_summary(value);
    let mut accounts = Vec::new();
    for (index, item) in items.iter().take(32).enumerate() {
        let mut account = basic["accounts"][index].clone();
        let info = &item["usage_info"];
        let tier = info["tier"]["label"]
            .as_str()
            .filter(|s| s.len() <= 80 && !s.chars().any(char::is_control));
        let updated = timestamp(&item["usage_updated_at"]);
        let age = updated
            .as_ref()
            .and_then(|v| chrono::DateTime::parse_from_rfc3339(v).ok())
            .map(|v| chrono::Utc::now().timestamp().saturating_sub(v.timestamp()));
        let stale = item["usage_stale"].as_bool().unwrap_or(true)
            || age.map(|n| n > 120 || n < -60).unwrap_or(true);
        account["tier"] = json!(tier);
        account["usageUpdatedAt"] = json!(updated);
        account["stale"] = json!(stale);
        account["probeFailed"] = json!(item
            .get("probe_error")
            .map(|v| !v.is_null() && v != "" && v != false)
            .unwrap_or(false));
        account["windows"] = json!([
            window(&info["current_5h"], "5 小时额度"),
            window(&info["weekly"], "每周额度")
        ]);
        // Do not echo raw IDs, probe errors, cookies, or arbitrary upstream fields.
        accounts.push(account);
    }
    Ok(
        json!({"readyAccounts":basic["readyAccounts"], "accounts":accounts,
        "checkedAt":chrono::Utc::now().timestamp(), "source":"gemini-web-health",
        "note":"网页账号池独立额度；内部 Credits 不是调用次数。账号池自动轮转，没有固定默认账号。"}),
    )
}

pub(crate) fn quota(id: &str) -> Result<Value, String> {
    let connection = list()?
        .into_iter()
        .find(|item| item.id == id)
        .ok_or("Unknown connection")?;
    if !connection.enabled {
        return Err("Connection is disabled".into());
    }
    if connection.credential_source != "gemini-web-client" {
        return Err("This connection has no supported web-pool quota adapter".into());
    }
    let base = validate(&connection)?;
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(8))
        .connect_timeout(Duration::from_secs(3))
        .redirect(reqwest::redirect::Policy::none())
        .no_proxy()
        .build()
        .map_err(|_| "Cannot create quota client")?;
    // The pool explicitly exposes /health without authentication.
    let value = get_json(
        &client,
        base.join("/health").map_err(|_| "Invalid health URL")?,
        "",
    )?;
    summary(&value)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn quota_preserves_unknown_zero_and_one_without_inventing_calls() {
        assert!(timestamp(&json!(1792504925.90214)).is_some());
        assert!(timestamp(&json!(true)).is_none());
        assert_eq!(
            window(&json!({"usage_level":0.18,"remaining_credits":1960}), "x")["remainingPercent"],
            82.0
        );
        assert_eq!(
            window(&json!({"usage_level":1}), "x")["remainingPercent"],
            0.0
        );
        assert_eq!(
            window(&json!({"usage_level":0}), "x")["remainingPercent"],
            100.0
        );
        for value in [
            json!({}),
            json!({"usage_level":true}),
            json!({"usage_level":-1}),
            json!({"usage_level":1.1}),
            json!({"usage_percentage":18}),
        ] {
            assert!(window(&value, "x")["remainingPercent"].is_null());
        }
    }
    #[test]
    fn sanitized_pool_result_drops_private_fields_and_marks_old_data() {
        let value = summary(&json!({"ready_accounts":2,"accounts":[{
            "id":"private@example.com","status":"AVAILABLE","cookie":"secret",
            "probe_error":"secret authentication message", "usage_stale":false,
            "usage_updated_at":"2020-01-01T00:00:00Z",
            "usage_info":{"tier":{"label":"Pro"},"weekly":{"usage_level":0.0}}
        }]}))
        .unwrap();
        assert_eq!(value["accounts"][0]["status"], "available");
        assert_eq!(value["accounts"][0]["stale"], true);
        assert_eq!(value["accounts"][0]["probeFailed"], true);
        assert!(!value.to_string().contains("secret"));
        assert!(!value.to_string().contains("private@"));
    }
}
