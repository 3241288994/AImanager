//! Display-only, user-confirmed tier prices, bound to the current subscription
//! period. Never used for routing, authorization or quota enforcement.
use codexmanager_core::storage::AccountSubscription;
use serde_json::Value;

pub(crate) fn monthly_usd(id: &str, plan: Option<&str>, subscription: Option<&AccountSubscription>) -> Option<i64> {
    let storage=crate::storage_helpers::open_storage()?;
    let raw=storage.get_app_setting("codex_profile.pro_tiers").ok()??;
    let confirmations:Value=serde_json::from_str(&raw).ok()?;
    resolve(confirmations.get(id)?,plan,subscription,codexmanager_core::storage::now_ts())
}

fn resolve(confirmation:&Value,plan:Option<&str>,subscription:Option<&AccountSubscription>,now:i64)->Option<i64> {
    if plan!=Some("pro") { return None; }
    let subscription=subscription?;
    let expires=subscription.expires_at?;
    if !subscription.has_subscription || expires<=now || confirmation.get("expiresAt")?.as_i64()?!=expires { return None; }
    let amount=confirmation.get("monthlyUsd")?.as_i64()?;
    [100,200,500].contains(&amount).then_some(amount)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    #[test]
    fn confirmations_never_override_free_unknown_or_a_new_subscription_period() {
        let subscription=AccountSubscription {account_id:"fixture".into(),has_subscription:true,account_plan_type:Some("pro".into()),plan_type:Some("pro".into()),expires_at:Some(200),renews_at:None,updated_at:1};
        let value=json!({"monthlyUsd":200,"expiresAt":200});
        assert_eq!(resolve(&value,Some("pro"),Some(&subscription),100),Some(200));
        assert_eq!(resolve(&value,Some("free"),Some(&subscription),100),None);
        assert_eq!(resolve(&value,None,Some(&subscription),100),None);
        assert_eq!(resolve(&value,Some("pro"),Some(&subscription),201),None);
        assert_eq!(resolve(&json!({"monthlyUsd":200,"expiresAt":300}),Some("pro"),Some(&subscription),100),None);
        assert_eq!(resolve(&json!({"monthlyUsd":999,"expiresAt":200}),Some("pro"),Some(&subscription),100),None);
    }
}
