#!/usr/bin/env bash
set -euo pipefail

repo_dir="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
cd "$repo_dir"

command -v rg >/dev/null 2>&1 || {
  echo "ripgrep (rg) is required for source and secret checks; preflight stopped" >&2
  exit 1
}

required=(Cargo.toml Cargo.lock LICENSE README.md INSTALL.md SECURITY.md apps/package.json apps/pnpm-lock.yaml labcontext-provider/pyproject.toml labcontext-provider/labcontext.example.toml)
for path in "${required[@]}"; do
  test -f "$path" || { echo "missing required file: $path" >&2; exit 1; }
done

blocked=$(find . \
  \( -path './.git' -o -path './target' -o -path './apps/node_modules' -o \
     -path './apps/.next' -o -path './apps/out' -o -path './apps/src-tauri/target' -o -path './apps/src-tauri/gen' -o -path './dist-open-source' -o \
     -path './apps/test-results' -o -path './apps/playwright-report' -o \
     -path './apps/blob-report' -o -path './data' \) -prune -o \
  -type f \( \
    -name '.env' -o -name '.env.local' -o -name 'auth.json' -o \
    -name 'codexmanager.rpc-token' -o -name '*.db' -o -name '*.sqlite' -o \
    -name '*.pem' -o -name '*.p12' -o -name '*.pfx' -o -name '*.key' -o \
    -name '*.token' -o -name '*.secret' -o -name 'codexmanager-web-access-password' -o \
    -name '.web-access-password' -o -name '*.log' -o -name '.app.json' \
  \) -not -path './deploy/.env.example' -print)
if [[ -n "$blocked" ]]; then
  echo "blocked sensitive/runtime files found:" >&2
  echo "$blocked" >&2
  exit 1
fi

if rg -n --hidden \
  -g '!**/.git/**' \
  -g '!apps/node_modules/**' \
  -g '!apps/.next/**' \
  -g '!apps/out/**' \
  -g '!apps/src-tauri/target/**' \
  -g '!apps/src-tauri/gen/**' \
  -g '!target/**' \
  -g '!dist-open-source/**' \
  -g '!CodexManager-open-source-prep-*.tar.gz' \
  -g '!Cargo.lock' \
  '(-----BEGIN [A-Z ]*PRIVATE KEY-----|sk-(proj-)?[A-Za-z0-9_-]{32,})' .; then
  echo "possible private key or API secret found" >&2
  exit 1
fi

# The public release must never inherit an upstream update feed at runtime.
# Attribution stays in README/NOTICE; executable source must require the
# maintainer to opt in to its own release repository.
if rg -n 'qxcnm/Codex-Manager' apps/src-tauri/src crates/service/src; then
  echo "upstream repository must not be hard-coded in executable source" >&2
  exit 1
fi

if rg -n --hidden \
  -g '!**/.git/**' \
  -g '!apps/node_modules/**' \
  -g '!apps/.next/**' \
  -g '!apps/out/**' \
  -g '!apps/src-tauri/target/**' \
  -g '!apps/src-tauri/gen/**' \
  -g '!target/**' \
  -g '!dist-open-source/**' \
  '(author\.qxnm\.top|registry\.cn-hangzhou\.aliyuncs\.com/kilimiao|ghcr\.io/qxcnm/)' .; then
  echo "personal deployment or upstream image reference found" >&2
  exit 1
fi

for personal_asset in \
  apps/public/author-alipay.jpg \
  apps/public/author-wechat.jpg \
  apps/public/author-wechat-pay.jpg \
  apps/public/sponsors/racknerd.gif \
  apps/public/sponsors/xingsiyan.jpg \
  assets/images/AliPay.jpg \
  assets/images/qq_group.jpg \
  assets/images/wechat.jpg \
  assets/images/wechatPay.jpg; do
  if [[ -e "$personal_asset" ]]; then
    echo "personal or promotional asset must be removed before publication: $personal_asset" >&2
    exit 1
  fi
done

python3 - <<'PY'
import json
from pathlib import Path

root = Path("plugins/codexmanager-connector")
manifest = json.loads((root / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
if manifest.get("name") != "codexmanager-connector":
    raise SystemExit("plugin manifest name does not match the public template directory")
if "apps" in manifest or "mcpServers" in manifest:
    raise SystemExit("public plugin template must not contain a user-specific connection")
if (root / ".app.json").exists():
    raise SystemExit("public plugin template contains .app.json")
PY

PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile \
  scripts/open-source/package.py \
  scripts/labcontext.py \
  scripts/labcontext_router.py \
  labcontext-provider/src/labcontext/document_extract.py \
  labcontext-provider/src/labcontext/direct_path.py
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s scripts/tests -p 'test_*.py'
if command -v cargo >/dev/null 2>&1 && cargo --version >/dev/null 2>&1; then
  cargo metadata --locked --no-deps --format-version 1 >/dev/null
  cargo metadata --manifest-path apps/src-tauri/Cargo.toml --locked --no-deps --format-version 1 >/dev/null
else
  echo "warning: usable cargo toolchain unavailable; skipped Rust manifest validation" >&2
fi

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  compose_secret_file="$(mktemp "${TMPDIR:-/tmp}/codexmanager-compose-secret.XXXXXX")"
  trap 'rm -f -- "$compose_secret_file"' EXIT
  CODEXMANAGER_WEB_ACCESS_PASSWORD_FILE_HOST="$compose_secret_file" \
    docker compose -f deploy/docker-compose.self-hosted.yml config --quiet
else
  echo "warning: Docker Compose unavailable; skipped compose rendering" >&2
fi

echo "open-source preflight passed"
