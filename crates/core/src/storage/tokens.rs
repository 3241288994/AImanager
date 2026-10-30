use rusqlite::{Result, Row};

use super::{Storage, Token};

impl Storage {
    /// 函数 `insert_token`
    ///
    /// 作者: gaohongshun
    ///
    /// 时间: 2026-04-02
    ///
    /// # 参数
    /// - self: 参数 self
    /// - token: 参数 token
    ///
    /// # 返回
    /// 返回函数执行结果
    pub fn insert_token(&self, token: &Token) -> Result<()> {
        self.conn.execute(
            "INSERT INTO tokens (account_id, id_token, access_token, refresh_token, api_key_access_token, last_refresh)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6)
             ON CONFLICT(account_id) DO UPDATE SET
                id_token = excluded.id_token,
                access_token = excluded.access_token,
                refresh_token = excluded.refresh_token,
                api_key_access_token = excluded.api_key_access_token,
                last_refresh = excluded.last_refresh",
            (
                &token.account_id,
                &token.id_token,
                &token.access_token,
                &token.refresh_token,
                &token.api_key_access_token,
                token.last_refresh,
            ),
        )?;
        Ok(())
    }

    /// 函数 `list_tokens_due_for_refresh`
    ///
    /// 作者: gaohongshun
    ///
    /// 时间: 2026-04-02
    ///
    /// # 参数
    /// - self: 参数 self
    /// - refresh_due_cutoff_ts: 参数 refresh_due_cutoff_ts
    /// - access_exp_cutoff_ts: 参数 access_exp_cutoff_ts
    /// - limit: 参数 limit
    ///
    /// # 返回
    /// 返回函数执行结果
    pub fn list_tokens_due_for_refresh(
        &self,
        refresh_due_cutoff_ts: i64,
        access_exp_cutoff_ts: i64,
        limit: usize,
    ) -> Result<Vec<Token>> {
        let mut stmt = self.conn.prepare(
            "WITH latest_status AS (
                SELECT
                    account_id,
                    message,
                    ROW_NUMBER() OVER (
                        PARTITION BY account_id
                        ORDER BY created_at DESC, id DESC
                    ) AS rn
                FROM events
                WHERE type = 'account_status_update'
             )
             SELECT tokens.account_id, tokens.id_token, tokens.access_token, tokens.refresh_token, tokens.api_key_access_token, tokens.last_refresh
             FROM tokens
             JOIN accounts ON accounts.id = tokens.account_id
             LEFT JOIN latest_status
               ON latest_status.account_id = tokens.account_id
              AND latest_status.rn = 1
             WHERE TRIM(COALESCE(refresh_token, '')) <> ''
               AND LOWER(TRIM(accounts.status)) NOT IN ('disabled', 'banned')
               AND (
                    latest_status.message IS NULL
                    OR (
                        latest_status.message NOT LIKE '% reason=account_deactivated'
                        AND latest_status.message NOT LIKE '% reason=workspace_deactivated'
                        AND latest_status.message NOT LIKE '% reason=refresh_token_region_blocked'
                    )
               )
               AND (
                    next_refresh_at IS NULL
                    OR next_refresh_at <= ?1
                    OR (
                        access_token_exp IS NOT NULL
                        AND access_token_exp <= ?2
                    )
               )
             ORDER BY COALESCE(tokens.next_refresh_at, 0) ASC, tokens.account_id ASC
             LIMIT ?3",
        )?;
        let mut rows = stmt.query((refresh_due_cutoff_ts, access_exp_cutoff_ts, limit as i64))?;
        let mut out = Vec::new();
        while let Some(row) = rows.next()? {
            out.push(map_token_row(row)?);
        }
        Ok(out)
    }

    /// 函数 `update_token_refresh_schedule`
    ///
    /// 作者: gaohongshun
    ///
    /// 时间: 2026-04-02
    ///
    /// # 参数
    /// - self: 参数 self
    /// - account_id: 参数 account_id
    /// - access_token_exp: 参数 access_token_exp
    /// - next_refresh_at: 参数 next_refresh_at
    ///
    /// # 返回
    /// 返回函数执行结果
    pub fn update_token_refresh_schedule(
        &self,
        account_id: &str,
        access_token_exp: Option<i64>,
        next_refresh_at: Option<i64>,
    ) -> Result<()> {
        self.conn.execute(
            "UPDATE tokens
             SET access_token_exp = ?1,
                 next_refresh_at = ?2
             WHERE account_id = ?3",
            (access_token_exp, next_refresh_at, account_id),
        )?;
        Ok(())
    }

    /// 函数 `touch_token_refresh_attempt`
    ///
    /// 作者: gaohongshun
    ///
    /// 时间: 2026-04-02
    ///
    /// # 参数
    /// - self: 参数 self
    /// - account_id: 参数 account_id
    /// - attempt_ts: 参数 attempt_ts
    ///
    /// # 返回
    /// 返回函数执行结果
    pub fn touch_token_refresh_attempt(&self, account_id: &str, attempt_ts: i64) -> Result<()> {
        self.conn.execute(
            "UPDATE tokens
             SET last_refresh_attempt_at = ?1
             WHERE account_id = ?2",
            (attempt_ts, account_id),
        )?;
        Ok(())
    }

    /// 函数 `token_count`
    ///
    /// 作者: gaohongshun
    ///
    /// 时间: 2026-04-02
    ///
    /// # 参数
    /// - self: 参数 self
    ///
    /// # 返回
    /// 返回函数执行结果
    pub fn token_count(&self) -> Result<i64> {
        self.conn
            .query_row("SELECT COUNT(1) FROM tokens", [], |row| row.get(0))
    }

    /// 函数 `list_tokens`
    ///
    /// 作者: gaohongshun
    ///
    /// 时间: 2026-04-02
    ///
    /// # 参数
    /// - self: 参数 self
    ///
    /// # 返回
    /// 返回函数执行结果
    pub fn list_tokens(&self) -> Result<Vec<Token>> {
        let mut stmt = self.conn.prepare(
            "SELECT account_id, id_token, access_token, refresh_token, api_key_access_token, last_refresh FROM tokens",
        )?;
        let mut rows = stmt.query([])?;
        let mut out = Vec::new();
        while let Some(row) = rows.next()? {
            out.push(map_token_row(row)?);
        }
        Ok(out)
    }

    /// 函数 `find_token_by_account_id`
    ///
    /// 作者: gaohongshun
    ///
    /// 时间: 2026-04-02
    ///
    /// # 参数
    /// - self: 参数 self
    /// - account_id: 参数 account_id
    ///
    /// # 返回
    /// 返回函数执行结果
    pub fn find_token_by_account_id(&self, account_id: &str) -> Result<Option<Token>> {
        let mut stmt = self.conn.prepare(
            "SELECT account_id, id_token, access_token, refresh_token, api_key_access_token, last_refresh
             FROM tokens
             WHERE account_id = ?1
             LIMIT 1",
        )?;
        let mut rows = stmt.query([account_id])?;
        if let Some(row) = rows.next()? {
            Ok(Some(map_token_row(row)?))
        } else {
            Ok(None)
        }
    }

    /// 函数 `ensure_token_api_key_column`
    ///
    /// 作者: gaohongshun
    ///
    /// 时间: 2026-04-02
    ///
    /// # 参数
    /// - super: 参数 super
    ///
    /// # 返回
    /// 返回函数执行结果
    pub(super) fn ensure_token_api_key_column(&self) -> Result<()> {
        if self.has_column("tokens", "api_key_access_token")? {
            return Ok(());
        }
        self.conn.execute(
            "ALTER TABLE tokens ADD COLUMN api_key_access_token TEXT",
            [],
        )?;
        Ok(())
    }

    /// 函数 `ensure_token_refresh_schedule_columns`
    ///
    /// 作者: gaohongshun
    ///
    /// 时间: 2026-04-02
    ///
    /// # 参数
    /// - super: 参数 super
    ///
    /// # 返回
    /// 返回函数执行结果
    pub(super) fn ensure_token_refresh_schedule_columns(&self) -> Result<()> {
        self.ensure_column("tokens", "access_token_exp", "INTEGER")?;
        self.ensure_column("tokens", "next_refresh_at", "INTEGER")?;
        self.ensure_column("tokens", "last_refresh_attempt_at", "INTEGER")?;
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tokens_next_refresh_at ON tokens(next_refresh_at)",
            [],
        )?;
        Ok(())
    }
}

/// 函数 `map_token_row`
///
/// 作者: gaohongshun
///
/// 时间: 2026-04-02
///
/// # 参数
/// - row: 参数 row
///
/// # 返回
/// 返回函数执行结果
fn map_token_row(row: &Row<'_>) -> Result<Token> {
    Ok(Token {
        account_id: row.get(0)?,
        id_token: row.get(1)?,
        access_token: row.get(2)?,
        refresh_token: row.get(3)?,
        api_key_access_token: row.get(4)?,
        last_refresh: row.get(5)?,
    })
}
