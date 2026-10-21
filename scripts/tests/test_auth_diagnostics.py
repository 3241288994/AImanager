"""OAuth failure classification is explicit, bounded and credential-free."""
import importlib.util
from pathlib import Path
import unittest

SOURCE = Path(__file__).resolve().parents[2] / "crates/service/src/ai_accounts/auth_diagnostics.py"
spec = importlib.util.spec_from_file_location("auth_diagnostics", SOURCE)
diagnostics = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diagnostics)


class AuthDiagnosticsTest(unittest.TestCase):
    def test_only_explicit_signals_get_a_specific_reason(self):
        cases = [
            ("OAuth error: Invalid code. Please make sure the full code was copied", "authorization_code_invalid"),
            ("Authorization code has expired", "authorization_code_expired"),
            ("The authorization code has already been used", "authorization_code_used"),
            ("OAuth error: state mismatch", "authorization_state_mismatch"),
            ("PKCE verification failed", "authorization_state_mismatch"),
            ("Token exchange failed: invalid_grant", "authorization_rejected"),
            ("access_denied", "authorization_denied"),
            ("Error: ECONNREFUSED", "network_unavailable"),
            ("OAuth error: timeout of 15000ms exceeded", "network_unavailable"),
            ("certificate verify failed", "network_unavailable"),
            ("Request failed with status code 503", "auth_service_unavailable"),
            ("HTTP 429", "auth_service_unavailable"),
            ("Could not save credentials in keychain", "credential_store_unavailable"),
            ("keychain is locked", "credential_store_unavailable"),
            ("unknown option --claudeai", "cli_incompatible"),
        ]
        for output, reason in cases:
            with self.subTest(reason=reason, output=output):
                self.assertEqual(diagnostics.login_failure(output)["reasonCode"], reason)

    def test_missing_evidence_is_not_labeled_as_a_network_or_account_failure(self):
        for output in ("", "Paste authorization code:", "Using a proxy and system keychain", "Unexpected exit"):
            with self.subTest(output=output):
                self.assertEqual(diagnostics.login_failure(output)["reasonCode"], "authorization_not_verified")
        self.assertIn("未细分原因", diagnostics.login_failure("invalid_grant")["message"])

    def test_session_timeout_and_status_check_failure_are_distinct(self):
        self.assertEqual(diagnostics.login_failure("request timed out", timed_out=True)["reasonCode"], "session_expired")
        self.assertEqual(diagnostics.login_failure("", status_note="Official CLI status check timed out")["reasonCode"], "auth_status_unavailable")
        self.assertEqual(diagnostics.login_failure("", status_note="This CLI version did not return supported auth JSON")["reasonCode"], "cli_incompatible")

    def test_diagnostics_never_echo_terminal_output_or_url_values(self):
        secrets = ("example-private-code", "example-private-state", "example-private-token", "person@example.invalid")
        output = "OAuth error: Invalid code. " + " ".join(secrets)
        result = diagnostics.login_failure(output)
        for secret in secrets:
            self.assertNotIn(secret, str(result))
        url = "https://example.invalid/oauth?code=invalid_grant&state=state_mismatch"
        self.assertEqual(diagnostics.login_failure(url)["reasonCode"], "authorization_not_verified")
        self.assertEqual(diagnostics.login_failure("invalid_grant\n" + "x" * 12001)["reasonCode"], "authorization_not_verified")

    def test_claude_callback_urls_are_rejected_without_echoing_their_values(self):
        for value in ("https://platform.claude.com/oauth/code/callback?code=example-private&state=example-state", " HTTPS://example.invalid/callback?code=example-private "):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "回调网址，不是授权返回码") as raised:
                diagnostics.validate_code(value, "claude")
            self.assertNotIn("example-private", str(raised.exception))

    def test_return_codes_keep_state_and_are_not_reinterpreted(self):
        self.assertEqual(diagnostics.validate_code("  example-code#example-state\n", "claude"), "example-code#example-state")
        # Preserve Antigravity's existing accepted input contract.
        self.assertEqual(diagnostics.validate_code("https://example.invalid/callback?code=example", "antigravity"), "https://example.invalid/callback?code=example")
        for value in (None, "", "x" * 2049, "not a code", "example;command", "secret\ncommand"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "返回码格式"):
                diagnostics.validate_code(value, "claude")


if __name__ == "__main__":
    unittest.main()
