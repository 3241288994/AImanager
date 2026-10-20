"""Read bounded, account-local CLI session metadata without changing native history."""
import datetime
import json
import os
from pathlib import Path
import re
import shlex
import sqlite3
import time
from urllib.parse import unquote, urlsplit

UUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\Z")
MAX_FILES = 1000
MAX_BYTES = 16 * 1024 * 1024
CHUNK = 64 * 1024


def safe(path, home):
    """Reject symlink components, including missing paths outside this profile."""
    try:
        relative = path.relative_to(home)
        return not home.is_symlink() and not any(
            home.joinpath(*relative.parts[:i]).is_symlink()
            for i in range(1, len(relative.parts) + 1)
        )
    except ValueError:
        return False


def text(value, size=240):
    return "".join(c for c in str(value or "") if c.isprintable())[:size]


def timestamp(value):
    try:
        if isinstance(value, (int, float)):
            return int(value if value > 1e11 else value * 1000)
        return int(datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp() * 1000)
    except (ValueError, TypeError, OverflowError):
        return 0


def command(root, account, session_id=None, cwd=None):
    # Pin both state root and account; resuming must not change the active account.
    argv = ["env", "AIMANAGER_STATE_DIR=" + str(root), "aimanager-cli", account["provider"],
            "--account-id", account["id"], "--"]
    argv += (["--resume" if account["provider"] == "claude" else "--conversation", session_id]
             if session_id else ["--continue"])
    result = shlex.join(argv)
    return ("cd -- " + shlex.quote(cwd) + " && " if cwd else "") + result


def entry(root, account, session_id, title, cwd, updated, source):
    if not isinstance(session_id, str) or not UUID.fullmatch(session_id):
        return None
    cwd = cwd if isinstance(cwd, str) and os.path.isabs(cwd) and len(cwd) <= 4096 and "\x00" not in cwd else None
    exists = bool(cwd and Path(cwd).is_dir())
    return {"id": session_id, "title": text(title) or session_id, "cwd": cwd,
            "updatedAtMs": updated, "source": source, "cwdExists": exists,
            "visibility": "ready" if exists else ("missing_workspace" if cwd else "unknown_workspace"),
            "resumeCommand": command(root, account, session_id, cwd)}


def claude(root, account, home, coverage, deadline):
    base = home / ".claude/projects"
    if not safe(base, home) or not base.is_dir():
        return []
    items, consumed = [], 0
    # Only project-level transcripts; never traverse subagents, plugins or links.
    with os.scandir(base) as projects:
        for index, project in enumerate(projects):
            if index >= MAX_FILES or time.monotonic() > deadline:
                coverage["partial"] = True
                break
            if not project.is_dir(follow_symlinks=False):
                continue
            with os.scandir(project.path) as files:
                for file in files:
                    if coverage["filesScanned"] >= MAX_FILES or consumed >= MAX_BYTES or time.monotonic() > deadline:
                        coverage["partial"] = True
                        return items
                    coverage["filesScanned"] += 1
                    path = Path(file.path)
                    if not UUID.fullmatch(path.stem) or path.suffix != ".jsonl" or not file.is_file(follow_symlinks=False):
                        continue
                    try:
                        size = file.stat(follow_symlinks=False).st_size
                        with path.open("rb") as stream:
                            head = stream.read(CHUNK)
                            tail = b""
                            if size > CHUNK:
                                stream.seek(max(CHUNK, size - CHUNK))
                                tail = stream.read(CHUNK)
                        consumed += len(head) + len(tail)
                        rows = []
                        for line in (head + b"\n" + tail).splitlines():
                            try:
                                row = json.loads(line)
                                if isinstance(row, dict) and row.get("sessionId", path.stem) == path.stem:
                                    rows.append(row)
                            except (ValueError, UnicodeError):
                                continue
                        cwd = next((r["cwd"] for r in rows if isinstance(r.get("cwd"), str)), None)
                        title = next((r.get("customTitle") or r.get("summary") for r in reversed(rows)
                                      if r.get("customTitle") or r.get("summary")), "")
                        if not title:
                            # A short first user prompt is the same title shown by the native CLI.
                            for row in rows:
                                if row.get("type") == "user" and not row.get("isSidechain"):
                                    message = row.get("message", {})
                                    content = message.get("content") if isinstance(message, dict) else None
                                    if isinstance(content, str):
                                        title = content
                                        break
                        item = entry(root, account, path.stem, title, cwd, int(file.stat().st_mtime * 1000), "claude_jsonl")
                        if item:
                            items.append(item)
                    except OSError:
                        coverage["partial"] = True
    return items


def workspace(value):
    try:
        parsed = json.loads(value)
    except (ValueError, TypeError):
        parsed = value
    values = parsed if isinstance(parsed, list) else [parsed]
    for value in values:
        if not isinstance(value, str):
            continue
        if value.startswith("/"):
            return value
        uri = urlsplit(value)
        if uri.scheme == "file" and uri.netloc in ("", "localhost"):
            return unquote(uri.path)
    return None


def antigravity(root, account, home, coverage, deadline, query, limit):
    path = home / ".gemini/antigravity-cli/conversation_summaries.db"
    if not safe(path, home) or not path.is_file():
        return [], 0
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=1) as db:
        db.execute("PRAGMA query_only=ON")
        db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        # Bound each string in SQL before materializing it in Python.
        predicate = " WHERE instr(lower(title), ?) > 0 OR instr(lower(conversation_id), ?) > 0 OR instr(lower(workspace_uris), ?) > 0"
        params = (query.lower(),) * 3
        total = db.execute("SELECT count(*) FROM conversation_summaries" + predicate, params).fetchone()[0]
        rows = db.execute(
            "SELECT substr(conversation_id,1,100),substr(title,1,240),substr(workspace_uris,1,8192),"
            "substr(last_modified_time,1,80) FROM conversation_summaries" + predicate +
            " ORDER BY last_modified_time DESC LIMIT ?", (*params, limit)).fetchall()
    coverage["filesScanned"] = 1
    items = [entry(root, account, sid, title, workspace(uris), timestamp(updated), "antigravity_sqlite")
             for sid, title, uris, updated in rows]
    if any(item is None for item in items):
        coverage["partial"] = True
    return [item for item in items if item], total


def catalog(root, account, home, query="", limit=100):
    if not isinstance(query, str) or len(query) > 200:
        raise ValueError("Session search must be at most 200 characters")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
        raise ValueError("Session limit must be between 1 and 500")
    coverage = {"filesScanned": 0, "partial": False}
    deadline = time.monotonic() + 4
    try:
        if account["provider"] == "claude":
            items = claude(root, account, home, coverage, deadline)
            items = [item for item in items if query.lower() in
                     (item["title"] + " " + (item["cwd"] or "") + " " + item["id"]).lower()]
            items.sort(key=lambda item: item["updatedAtMs"], reverse=True)
            total, items = len(items), items[:limit]
        elif account["provider"] == "antigravity":
            items, total = antigravity(root, account, home, coverage, deadline, query, limit)
        else:
            raise ValueError("Unsupported session provider")
    except (OSError, sqlite3.Error):
        raise ValueError("CLI 会话索引暂不可读或结构不兼容，请刷新后重试") from None
    bounded, size = [], 0
    for item in items:
        size += len(json.dumps(item, ensure_ascii=False).encode("utf-8"))
        if size > 512 * 1024:
            coverage["partial"] = True
            break
        bounded.append(item)
    items = bounded
    return {"accountId": account["id"], "provider": account["provider"], "items": items,
            "total": total, "coverage": coverage, "checkedAt": int(time.time()),
            "continueCommand": command(root, account),
            "note": ("读取本账号项目日志的首尾元数据，超出读取边界时标记部分结果。"
                     if account["provider"] == "claude" else
                     "只读官方本地会话索引；索引条目不保证云端会话仍可访问，恢复由官方 CLI 完成。")}
