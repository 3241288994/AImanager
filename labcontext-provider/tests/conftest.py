"""Keep unit tests independent from the developer's installed optional bridge."""
import pytest


@pytest.fixture(autouse=True)
def isolate_optional_collaboration(monkeypatch, tmp_path):
    monkeypatch.setenv("AI_COLLAB_BIN", str(tmp_path / "no-installed-collaboration"))
