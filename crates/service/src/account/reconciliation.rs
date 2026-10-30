//! Conservative reconciliation of legacy IDs, without deleting credentials or history.
use codexmanager_core::{
    auth::parse_id_token_claims,
    storage::{Account, Storage, Token},
};
use std::collections::{HashMap, HashSet};

type Identity = (String, String, String, String);

fn identity(account: &Account, token: &Token) -> Option<Identity> {
    let claims = parse_id_token_claims(&token.id_token).ok()?;
    let subject = claims.sub.trim();
    let issuer = account.issuer.trim();
    let chatgpt = account.chatgpt_account_id.as_deref()?.trim();
    let workspace = account.workspace_id.as_deref()?.trim();
    if [subject, issuer, chatgpt, workspace]
        .iter()
        .any(|part| part.is_empty())
    {
        return None;
    }
    // Do not use email, plan, or an unqualified account ID as identity evidence.
    Some((
        issuer.into(),
        subject.into(),
        chatgpt.into(),
        workspace.into(),
    ))
}

pub(crate) fn duplicates(accounts: &[Account], tokens: &[Token]) -> Vec<(String, String)> {
    let tokens: HashMap<_, _> = tokens
        .iter()
        .map(|token| (token.account_id.as_str(), token))
        .collect();
    let mut groups: HashMap<Identity, Vec<(&Account, &Token)>> = HashMap::new();
    for account in accounts {
        if let Some(token) = tokens.get(account.id.as_str()) {
            if let Some(key) = identity(account, token) {
                groups.entry(key).or_default().push((account, token));
            }
        }
    }
    let mut result = Vec::new();
    for mut group in groups.into_values() {
        group.sort_by_key(|(account, token)| {
            std::cmp::Reverse((
                account.status == "active",
                token.last_refresh,
                account.created_at,
                account.id.as_str(),
            ))
        });
        let (canonical, _) = group[0];
        if canonical.status != "active" {
            continue;
        }
        for (old, _) in group.iter().skip(1) {
            result.push((old.id.clone(), canonical.id.clone()));
        }
    }
    result
}

pub(crate) fn visible_accounts(
    storage: &Storage,
    mut accounts: Vec<Account>,
) -> Result<Vec<Account>, String> {
    let tokens = storage.list_tokens().map_err(|e| e.to_string())?;
    let hidden: HashSet<_> = duplicates(&accounts, &tokens)
        .into_iter()
        .map(|(old, _)| old)
        .collect();
    accounts.retain(|account| !hidden.contains(&account.id));
    Ok(accounts)
}

pub(crate) fn reconcile(storage: &Storage) -> Result<(), String> {
    let accounts = storage.list_accounts().map_err(|e| e.to_string())?;
    let tokens = storage.list_tokens().map_err(|e| e.to_string())?;
    for (old, canonical) in duplicates(&accounts, &tokens) {
        // The standard disabled state also excludes the old credentials from
        // gateway selection and periodic usage refresh. All history stays intact.
        crate::account_status::set_account_status(
            storage,
            &old,
            "disabled",
            &format!("superseded_by:{canonical}"),
        );
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use base64::Engine;

    fn sample(id: &str, subject: &str, workspace: &str, fresh: i64) -> (Account, Token) {
        let payload = base64::engine::general_purpose::URL_SAFE_NO_PAD
            .encode(serde_json::json!({"sub": subject}).to_string());
        (
            Account {
                id: id.into(),
                label: "same@example.test".into(),
                issuer: "issuer".into(),
                chatgpt_account_id: Some("cgpt".into()),
                workspace_id: Some(workspace.into()),
                group_name: None,
                sort: 0,
                status: "active".into(),
                created_at: fresh,
                updated_at: fresh,
            },
            Token {
                account_id: id.into(),
                id_token: format!("e30.{payload}.sig"),
                access_token: "access".into(),
                refresh_token: "refresh".into(),
                api_key_access_token: None,
                last_refresh: fresh,
            },
        )
    }

    #[test]
    fn keeps_new_credentials_and_history_and_is_idempotent() {
        let storage = Storage::open_in_memory().unwrap();
        storage.init().unwrap();
        for (a, t) in [
            sample("old", "sub", "org", 1),
            sample("new", "sub", "org", 2),
        ] {
            storage.insert_account(&a).unwrap();
            storage.insert_token(&t).unwrap();
        }
        reconcile(&storage).unwrap();
        reconcile(&storage).unwrap();
        assert_eq!(storage.account_count().unwrap(), 2);
        assert_eq!(storage.token_count().unwrap(), 2);
        assert_eq!(storage.event_count().unwrap(), 1);
        assert_eq!(
            storage.find_account_by_id("old").unwrap().unwrap().status,
            "disabled"
        );
        let due = storage
            .list_tokens_due_for_refresh(i64::MAX, i64::MAX, 100)
            .unwrap();
        assert_eq!(due.len(), 1);
        assert_eq!(due[0].account_id, "new");
        let visible = visible_accounts(&storage, storage.list_accounts().unwrap()).unwrap();
        assert_eq!(visible.len(), 1);
        assert_eq!(visible[0].id, "new");
    }

    #[test]
    fn never_merges_same_email_across_subject_workspace_or_issuer() {
        let entries = [
            sample("a", "one", "org-a", 1),
            sample("b", "two", "org-a", 2),
            sample("c", "one", "org-b", 3),
        ];
        let mut accounts: Vec<_> = entries.iter().map(|(a, _)| a.clone()).collect();
        let mut tokens: Vec<_> = entries.iter().map(|(_, t)| t.clone()).collect();
        let (mut a, t) = sample("d", "one", "org-a", 4);
        a.issuer = "other".into();
        accounts.push(a);
        tokens.push(t);
        assert!(duplicates(&accounts, &tokens).is_empty());
        tokens[0].id_token = "malformed".into();
        assert!(duplicates(&accounts, &tokens).is_empty());
    }
}
