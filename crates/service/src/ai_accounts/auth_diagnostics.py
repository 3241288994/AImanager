"""Bounded OAuth diagnostics. Never return CLI output, URLs, or credentials."""
import re


MESSAGES = {
    "authorization_url_not_code": "粘贴的是回调网址，不是授权返回码。请在官方授权页点击“复制授权码 / Copy code”，将完整返回码粘贴到当前窗口；不要复制地址栏网址。",
    "authorization_input_invalid": "返回码格式不正确或超过长度限制。请重新复制官方页面显示的完整返回码，不要输入密码、网址或终端命令。",
    "authorization_code_invalid": "官方客户端报告返回码无效。请检查是否完整复制；若已尝试过，请重新发起授权，不要重复提交旧码。",
    "authorization_code_expired": "官方客户端报告返回码已过期。请关闭本次窗口，重新发起网页登录并及时提交新码。",
    "authorization_code_used": "官方客户端报告返回码已使用。请重新发起授权，不要重复提交同一个码。",
    "authorization_state_mismatch": "官方客户端报告授权会话不匹配。请关闭旧授权页，从当前 AImanager 窗口重新发起，并只提交这次生成的返回码。",
    "authorization_rejected": "官方服务拒绝兑换返回码（invalid_grant），但未细分原因。返回码可能已过期、已使用或不属于本次会话，请重新发起授权。",
    "authorization_denied": "官方服务报告授权被拒绝或取消。请确认授权页面已完成同意；不要反复提交旧码，也不代表账号已被封禁。",
    "session_expired": "本次授权会话已超过等待时限。请重新发起网页登录；新码必须提交到生成该授权链接的同一个窗口。",
    "network_unavailable": "服务主机无法连接官方认证服务。请检查服务主机的代理、DNS、TLS 与网络后重新授权；浏览器能打开页面不代表服务器也能连接。",
    "auth_service_unavailable": "官方认证服务暂时不可用或请求过于频繁。请稍后重新发起授权，不要连续重试旧码。",
    "credential_store_unavailable": "官方客户端无法保存授权凭证。请检查服务主机独立配置目录的写权限、磁盘空间及钥匙串状态，不要删除已有凭证。",
    "cli_incompatible": "服务主机的官方 CLI 不支持当前登录或状态检查接口。请检查 CLI 版本及原生可执行文件路径，不要把托管启动器当成原生 CLI。",
    "auth_status_unavailable": "登录状态检查未完成，暂不能确认授权是否已保存。请先同步登录状态；仍未登录时再重新授权，避免重复提交返回码。",
    "authorization_not_verified": "官方客户端未确认登录，且未返回可识别的具体原因。请先同步登录状态；仍未登录时，从当前窗口重新授权并复制官方返回码，而不是回调网址。",
}


def diagnostic(reason):
    return {"reasonCode": reason, "message": MESSAGES[reason]}


def validate_code(value, provider):
    if not isinstance(value, str):
        raise ValueError(MESSAGES["authorization_input_invalid"])
    value = value.strip()
    if provider == "claude" and re.match(r"https?://", value, re.I):
        raise ValueError(MESSAGES["authorization_url_not_code"])
    if not re.fullmatch(r"[A-Za-z0-9_.~:#/@?=&%+\-]{1,2048}", value):
        raise ValueError(MESSAGES["authorization_input_invalid"])
    return value


# Only explicit error signals are classified. Prompt text mentioning a proxy,
# keychain, code, or state alone is not evidence that any of them failed.
ERROR_PATTERNS = (
    ("authorization_state_mismatch", r"\bstate[_ -]mismatch\b|\binvalid[_ ]state\b|\bstate (?:parameter )?(?:does not match|mismatch)|\b(?:pkce|code[_ ]verifier).{0,60}(?:mismatch|verification failed|invalid)"),
    ("authorization_code_expired", r"\b(?:authorization |login )?code (?:has |is )?(?:already )?expired\b|\bexpired (?:authorization |login )?code\b"),
    ("authorization_code_used", r"\b(?:authorization |login )?code.{0,45}(?:already (?:been )?used|already redeemed)|\bcode_already_used\b"),
    ("authorization_code_invalid", r"\b(?:invalid|incorrect) (?:authorization |login )?code\b|\b(?:authorization |login )?code (?:is )?(?:invalid|incorrect)\b"),
    ("authorization_rejected", r"\binvalid_grant\b"),
    ("authorization_denied", r"\baccess_denied\b|\bauthorization (?:was )?(?:denied|cancelled|canceled)\b|\buser denied\b"),
    ("credential_store_unavailable", r"(?:failed|unable|cannot|could not|error).{0,80}(?:sav\w* credential|writ\w* credential|keyring|keychain|secret service|dbus)|(?:keyring|keychain|secret service|dbus).{0,80}(?:unavailable|denied|locked|error|failed)|(?:EACCES|permission denied).{0,100}credential|credential.{0,100}(?:EACCES|permission denied)"),
    ("cli_incompatible", r"\b(?:unknown|unrecognized|unsupported) (?:command|option|argument)\b|\bno such command\b"),
    ("auth_service_unavailable", r"\b(?:HTTP|status(?: code)?)\s*[:=]?\s*(?:429|5\d\d)\b|\btoo many requests\b|\brate_limit(?:_error|_exceeded)?\b|\bservice unavailable\b"),
    ("network_unavailable", r"\b(?:ECONN\w*|ENOTFOUND|ETIMEDOUT|CERT_\w*|ERR_TLS_\w*)\b|\b(?:connection refused|failed to connect|network (?:error|unreachable)|unexpected EOF|certificate (?:verify|verification) failed|unable to verify.{0,30}certificate|self[- ]signed certificate|TLS (?:error|handshake failed)|DNS (?:error|resolution failed)|proxy (?:connection|authentication|tunnel) (?:failed|error)|request timed out|connection timed out)\b|\b(?:error|failed).{0,40}\b(?:timeout|timed out)\b"),
)


def detect_login_failure(output):
    # Output is examined in memory only. Remove URLs before matching so query
    # values cannot be mistaken for diagnostic evidence; never return excerpts.
    window = re.sub(r"https?://\S+", "[url]", output[-12000:], flags=re.I)
    for reason, pattern in ERROR_PATTERNS:
        if re.search(pattern, window, re.I):
            return diagnostic(reason)
    return None


def login_failure(output, timed_out=False, status_note=""):
    status_note = status_note or ""
    if timed_out:
        return diagnostic("session_expired")
    known = detect_login_failure(output)
    if known:
        return known
    if "supported auth JSON" in status_note or "supported auth status" in status_note:
        return diagnostic("cli_incompatible")
    if "status check timed out" in status_note or "safe limit" in status_note:
        return diagnostic("auth_status_unavailable")
    return diagnostic("authorization_not_verified")
