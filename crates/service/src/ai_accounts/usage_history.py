"""Bounded account-scoped CLI metrics. Never return conversation content."""
import fcntl
import json
import math
import os
from pathlib import Path
import time
import uuid
from datetime import datetime, timezone


def number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 0 <= value <= 10**15 else None


def windows(quota):
    result = []
    for item in quota.get("windows", [])[:16]:
        if not isinstance(item, dict):
            continue
        remaining = number(item.get("remainingPercent"))
        label = item.get("label")
        if remaining is None or remaining > 100 or not isinstance(label, str) or len(label) > 100:
            continue
        reset = item.get("resetsAt")
        result.append({"label": label, "remainingPercent": remaining,
                       "resetsAt": reset if isinstance(reset, str) and len(reset) < 120 else None})
    return result


def history_path(root, account_id):
    directory = root / "usage-history"
    directory.mkdir(mode=0o700, exist_ok=True)
    if directory.is_symlink():
        raise ValueError("Usage history directory cannot be a symlink")
    return directory / (account_id + ".json")


def read_history(path):
    if not path.exists():
        return []
    if path.is_symlink() or path.stat().st_size > 1048576:
        raise ValueError("Invalid usage history file")
    data = json.loads(path.read_text())
    if not isinstance(data, list):
        raise ValueError("Invalid usage history")
    return data


def record_snapshot(root, item):
    quota = item.get("quota", {})
    captured = number(quota.get("checkedAt"))
    cleaned = windows(quota)
    if quota.get("state") != "available" or not captured or not cleaned:
        return
    path = history_path(root, item["id"])
    with path.with_suffix(".lock").open("a") as lock:
        os.chmod(lock.name, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        rows = read_history(path)
        if rows and rows[-1]["capturedAt"] >= captured:
            return
        row = {"capturedAt": captured, "windows": cleaned}
        # Keep only the latest observation of each UTC day, for at most 366 days.
        same_hour = rows and int(rows[-1]["capturedAt"] // 3600) == int(captured // 3600)
        if same_hour:
            rows[-1] = row
        else:
            rows.append(row)
        daily = {}
        for previous in rows:
            day = int(previous["capturedAt"] // 86400)
            daily[day] = previous
        rows = [daily[key] for key in sorted(daily)[-366:]]
        temporary = path.with_name("." + uuid.uuid4().hex + ".tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(rows, stream)
        os.replace(temporary, path)


def date_range(start, end):
    try:
        a = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        b = datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        if a.strftime("%Y-%m-%d") != start or b.strftime("%Y-%m-%d") != end or not 0 < (b - a).days <= 366:
            raise ValueError()
        return a.timestamp(), b.timestamp()
    except (ValueError, TypeError):
        raise ValueError("Choose a valid range of at most 366 days")


def claude_days(home, start, end):
    root = home / ".claude/projects"
    totals = {}
    messages = {}
    scanned = 0
    consumed = 0
    partial = False
    deadline = time.monotonic() + 8
    if root.is_symlink():
        return [], {"filesScanned": 0, "partial": True}
    for directory, dirs, files in os.walk(root, followlinks=False):
        if time.monotonic() > deadline:
            partial = True
            break
        depth = len(Path(directory).relative_to(root).parts)
        dirs[:] = sorted(d for d in dirs if depth < 3 and not (Path(directory) / d).is_symlink())[:1000]
        for name in sorted(files):
            if not name.endswith(".jsonl"):
                continue
            path = Path(directory) / name
            if path.is_symlink() or not path.is_file():
                continue
            if scanned >= 1000 or consumed >= 64 * 1024 * 1024 or time.monotonic() > deadline:
                partial = True
                break
            scanned += 1
            try:
                with path.open("rb") as stream:
                    while True:
                        raw = stream.readline(1048577)
                        if not raw:
                            break
                        consumed += len(raw)
                        if len(raw) > 1048576 or consumed > 64 * 1024 * 1024 or time.monotonic() > deadline:
                            partial = True
                            break
                        try:
                            item = json.loads(raw)
                            if not isinstance(item, dict) or item.get("type") != "assistant":
                                continue
                            message = item.get("message", {})
                            usage = message.get("usage", {})
                            stamp = datetime.fromisoformat(item["timestamp"].replace("Z", "+00:00"))
                            if stamp.tzinfo is None or not start <= stamp.timestamp() < end:
                                continue
                            mid = message.get("id")
                            if not isinstance(mid, str) or not mid:
                                continue
                            values = [number(usage.get(k)) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")]
                            if values[0] is None or values[3] is None:
                                continue
                            # Cache fields absent from older native logs mean no cache usage.
                            for i in (1, 2):
                                if values[i] is None:
                                    key = ("cache_creation_input_tokens", "cache_read_input_tokens")[i - 1]
                                    if key in usage:
                                        raise ValueError("Invalid cache counter")
                                    values[i] = 0
                            previous = messages.get(mid)
                            candidate = (stamp.astimezone(timezone.utc).date().isoformat(), values)
                            # Streaming chunks repeat IDs; retain the greatest observed output count.
                            if previous is None or values[3] >= previous[1][3]:
                                messages[mid] = candidate
                        except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
                            continue
            except OSError:
                partial = True
        if partial and (consumed >= 64 * 1024 * 1024 or scanned >= 1000 or time.monotonic() > deadline):
            break
    captured = int(time.time())
    for day, values in messages.values():
        row = totals.setdefault(day, {"credits": None, "turns": 0, "uncachedInputTokens": 0,
                                    "cachedInputTokens": 0, "outputTokens": 0, "totalTokens": 0})
        row["turns"] += 1
        row["uncachedInputTokens"] += values[0] + values[1]
        row["cachedInputTokens"] += values[2]
        row["outputTokens"] += values[3]
        row["totalTokens"] += sum(values)
    return [{"date": key, "totals": totals[key], "capturedAt": captured} for key in sorted(totals)], {"filesScanned": scanned, "partial": partial}


def report(root, item, home, start_date, end_date):
    start, end = date_range(start_date, end_date)
    record_snapshot(root, item)
    history = [row for row in read_history(history_path(root, item["id"])) if start <= row["capturedAt"] < end]
    days, coverage = claude_days(home, start, end) if item["provider"] == "claude" else ([], {"filesScanned": 0, "partial": False})
    return {"accountId": item["id"], "provider": item["provider"], "startDate": start_date, "endDate": end_date,
            "source": "claude-local-jsonl" if item["provider"] == "claude" else "official-quota-snapshots",
            "days": days, "quotaHistory": history, "coverage": coverage, "checkedAt": int(time.time()),
            "note": ("仅统计本机该托管账号保留的 CLI 日志；未保存的会话不计入，模型回复次数不等于用户交互轮数。缓存写入计入未缓存输入。"
                     if item["provider"] == "claude" else "官方 CLI 暂未提供可靠的逐日 Token 明细；展示采集到的额度快照，不将额度差值推算为累计消耗。")}
