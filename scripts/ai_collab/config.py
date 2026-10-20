import copy
import json
import os
from pathlib import Path
import re
import tempfile


class CollabError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def user_home():
    return Path(os.environ.get("AI_COLLAB_HOME", str(Path.home()))).resolve()


def provider_path(value):
    """Resolve configured paths against the installer owner, not a harness's isolated HOME."""
    value = str(value)
    if value == "~" or value.startswith("~/"):
        return (user_home() / value[2:]).resolve()
    return Path(value).expanduser().resolve()


def config_path():
    return provider_path(os.environ.get("AI_COLLAB_CONFIG", "~/.config/ai-collab/config.json"))


def state_path():
    return provider_path(os.environ.get("AI_COLLAB_STATE_DIR", "~/.local/state/ai-collab"))


def defaults():
    return {
        "schemaVersion": 1,
        "claude": {
            "binary": "~/.local/share/aimanager/bin/claude",
            "managerRoot": "~/.local/state/aimanager",
        },
        "geminiWeb": {"envFile": "~/.config/gemini-web-client/client.env"},
        "codex": {"binary": "codex", "home": "~/.codex"},
        "hosts": {},
        "proxy": None,
        "models": {
            "opus5.5": {
                "provider": "claude-code", "model": "claude-opus-5-5",
                "minCliVersion": "2.1.280",
                "aliases": ["opus 5.5", "opus-5.5", "claude opus5.5", "claude-opus-5-5"],
            },
            "gemini4": {
                "provider": "gemini-web", "model": "gemini-argon",
                "aliases": ["gemini 4", "gemini4 argon", "gemini-argon", "gemini-4-argon"],
            },
        },
        "defaults": {"claude": "opus5.5", "gemini": "gemini4"},
    }


def normalize(value):
    return re.sub(r"[\s._-]+", "", value).lower()


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix="." + path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def read_json(path, limit=2 * 1024 * 1024):
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise CollabError("file_too_large", "JSON exceeds the configured size limit")
    return json.loads(raw)


def load():
    path = config_path()
    if not path.is_file():
        raise CollabError("not_initialized", "Run ai-collab init first")
    return validate(read_json(path))


def validate(value):
    if not isinstance(value, dict) or value.get("schemaVersion") != 1:
        raise CollabError("invalid_config", "Unsupported configuration version")
    if not isinstance(value.get("models"), dict) or not isinstance(value.get("defaults"), dict):
        raise CollabError("invalid_config", "models and defaults must be objects")
    if not all(isinstance(value.get(key), dict) for key in ("claude", "geminiWeb")):
        raise CollabError("invalid_config", "Provider configuration must be an object")
    names = {}
    for name, model in value.get("models", {}).items():
        if (not isinstance(model, dict) or not isinstance(model.get("aliases", []), list)
                or not all(isinstance(alias, str) for alias in model.get("aliases", []))):
            raise CollabError("invalid_config", "Invalid model entry or alias list")
        if model.get("provider") not in {"claude-code", "gemini-web", "codex-cli"}:
            raise CollabError("invalid_config", "Unsupported model provider")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/\[\]-]{0,159}", model.get("model", "")):
            raise CollabError("invalid_config", "Invalid upstream model ID")
        for alias in [name] + model.get("aliases", []):
            key = normalize(alias)
            if not key or (key in names and names[key] != name):
                raise CollabError("ambiguous_alias", "Model aliases must resolve unambiguously")
            names[key] = name
    for alias, target in value.get("defaults", {}).items():
        if not isinstance(target, str) or target not in value.get("models", {}):
            raise CollabError("invalid_config", "Default model references an unknown entry")
        if normalize(alias) in names:
            raise CollabError("ambiguous_alias", "Default alias conflicts with a versioned alias")
        expected = {"claude": "claude-code", "gemini": "gemini-web", "codex": "codex-cli"}.get(alias)
        if not expected or value["models"][target]["provider"] != expected:
            raise CollabError("provider_mismatch", "Provider defaults must preserve their invocation channel")
    return value


def resolve(config, requested):
    key = normalize(requested)
    for alias, name in config.get("defaults", {}).items():
        if key == normalize(alias):
            requested = name
            key = normalize(name)
            break
    for name, model in config["models"].items():
        if key in [normalize(x) for x in [name] + model.get("aliases", [])]:
            return dict(copy.deepcopy(model), name=name)
    raise CollabError("unknown_model", "Unknown model alias; use models or register the exact provider/model with alias set")
