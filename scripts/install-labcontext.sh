#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
install_root="${LABCONTEXT_INSTALL_ROOT:-$HOME/.local/lib/codexmanager}"
bin_dir="${LABCONTEXT_BIN_DIR:-$HOME/.local/bin}"

mkdir -p "$install_root" "$bin_dir"
install -m 0755 "$script_dir/labcontext.py" "$install_root/labcontext.py"
install -m 0755 "$script_dir/labcontext_router.py" "$install_root/labcontext_router.py"
for module in labcontext_connections labcontext_tunnel_control labcontext_connection_cli; do
  install -m 0644 "$script_dir/$module.py" "$install_root/$module.py"
done
ln -sfn "$install_root/labcontext.py" "$bin_dir/labcontext"

echo "installed labcontext to $bin_dir/labcontext"
echo "next: labcontext init local|server|hybrid"
