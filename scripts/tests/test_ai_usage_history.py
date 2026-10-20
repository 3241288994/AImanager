import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[2] / "crates/service/src/ai_accounts/usage_history.py"
spec = importlib.util.spec_from_file_location("usage_history", SOURCE)
usage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(usage)


class UsageHistoryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.logs = self.home / ".claude/projects/example"
        self.logs.mkdir(parents=True)
        self.start, self.end = usage.date_range("2026-10-20", "2026-10-21")
        self.item = {"id": "a" * 32, "provider": "claude", "quota": {
            "state": "available", "checkedAt": self.start + 100,
            "windows": [{"label": "5 小时额度", "remainingPercent": 82, "resetsAt": None}]}}

    def tearDown(self):
        self.temp.cleanup()

    def message(self, mid="one", output=10, timestamp="2026-10-20T01:00:00Z"):
        return {"type": "assistant", "timestamp": timestamp, "message": {
            "id": mid, "content": [{"text": "PRIVATE CONTENT MUST NOT LEAVE THE PARSER"}],
            "usage": {"input_tokens": 100, "cache_creation_input_tokens": 20,
                      "cache_read_input_tokens": 40, "output_tokens": output}}}

    def test_streaming_duplicates_and_copied_logs_count_once(self):
        rows = [self.message(output=3), self.message(output=12), self.message("outside", timestamp="2026-10-19T12:00:00Z")]
        for name in ("a.jsonl", "b.jsonl"):
            (self.logs / name).write_text("\n".join(json.dumps(row) for row in rows))
        days, coverage = usage.claude_days(self.home, self.start, self.end)
        self.assertEqual(days[0]["totals"], {"credits": None, "turns": 1, "uncachedInputTokens": 120,
                                          "cachedInputTokens": 40, "outputTokens": 12, "totalTokens": 172})
        self.assertFalse(coverage["partial"])
        self.assertNotIn("PRIVATE CONTENT", json.dumps(days))

    def test_timezone_conversion_and_invalid_counters(self):
        good = self.message(timestamp="2026-10-21T01:00:00+08:00")
        invalid = self.message("invalid")
        invalid["message"]["usage"]["output_tokens"] = True
        (self.logs / "log.jsonl").write_text(json.dumps(good) + "\n" + json.dumps(invalid))
        days, _ = usage.claude_days(self.home, self.start, self.end)
        self.assertEqual(days[0]["date"], "2026-10-20")
        self.assertEqual(days[0]["totals"]["turns"], 1)

    def test_symlinked_logs_do_not_cross_account_boundary(self):
        outside = self.root / "outside.jsonl"
        outside.write_text(json.dumps(self.message()))
        (self.logs / "link.jsonl").symlink_to(outside)
        days, _ = usage.claude_days(self.home, self.start, self.end)
        self.assertEqual(days, [])

    def test_oversized_line_reports_partial_instead_of_unbounded_read(self):
        (self.logs / "large.jsonl").write_text("x" * 1048578)
        days, coverage = usage.claude_days(self.home, self.start, self.end)
        self.assertEqual(days, [])
        self.assertTrue(coverage["partial"])

    def test_daily_history_keeps_newest_and_is_account_scoped(self):
        usage.record_snapshot(self.root, self.item)
        self.item["quota"]["checkedAt"] += 3600
        self.item["quota"]["windows"][0]["remainingPercent"] = 70
        usage.record_snapshot(self.root, self.item)
        self.item["quota"]["checkedAt"] -= 3600
        usage.record_snapshot(self.root, self.item)
        rows = usage.read_history(usage.history_path(self.root, self.item["id"]))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["windows"][0]["remainingPercent"], 70)
        self.assertEqual(usage.read_history(usage.history_path(self.root, "b" * 32)), [])
        self.assertEqual(usage.history_path(self.root, self.item["id"]).stat().st_mode & 0o777, 0o600)

    def test_unavailable_quotas_are_not_fabricated_and_range_is_enforced(self):
        self.item["provider"] = "antigravity"
        self.item["quota"] = {"state": "unavailable", "windows": []}
        report = usage.report(self.root, self.item, self.home, "2026-10-20", "2026-10-21")
        self.assertEqual(report["days"], [])
        self.assertEqual(report["quotaHistory"], [])
        for start, end in [("2026-10-21", "2026-10-20"), ("2020-01-01", "2026-10-20"), ("bad", "bad")]:
            with self.assertRaises(ValueError):
                usage.date_range(start, end)


if __name__ == "__main__":
    unittest.main()
