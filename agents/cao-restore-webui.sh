#!/usr/bin/env bash
# Rebuild CAO's web UI and put it back into the installed package.
#
# Why this exists: the PyPI wheel for cli-agent-orchestrator ships without the
# compiled frontend (awslabs/cli-agent-orchestrator#610). Their own
# pyproject.toml declares `src/cli_agent_orchestrator/web_ui/**` as package
# data and vite writes exactly there — the wheel is simply built without
# running `npm run build` first. So the assets are missing, the server skips
# its StaticFiles mount, and http://127.0.0.1:9889/ answers 404 JSON instead of
# the dashboard.
#
# Any `cao update` or reinstall replaces the package and wipes the fix. Re-run
# this script afterwards.
#
# Usage:  bash agents/cao-restore-webui.sh [path-to-cao-checkout]

set -euo pipefail

CHECKOUT="${1:-$HOME/gitbase/cli-agent-orchestrator}"

if [[ ! -d "$CHECKOUT/web" ]]; then
    echo "No CAO checkout with a web/ directory at: $CHECKOUT" >&2
    echo "Clone it first, matching your installed version:" >&2
    echo "  git clone --depth 1 --branch v\$(cao --version | grep -oE '[0-9]+\.[0-9]+\.[0-9]+') \\" >&2
    echo "      https://github.com/awslabs/cli-agent-orchestrator.git $CHECKOUT" >&2
    exit 1
fi

# Locate the installed package rather than hardcoding a Python version in the
# path — a uv tool upgrade can move it between python3.13/python3.14.
TARGET="$(
    "$(dirname "$(command -v cao)")/../share/uv/tools/cli-agent-orchestrator/bin/python" - <<'PY' 2>/dev/null || true
import pathlib, cli_agent_orchestrator
print(pathlib.Path(cli_agent_orchestrator.__file__).parent)
PY
)"
if [[ -z "$TARGET" ]]; then
    TARGET="$(find "$HOME/.local/share/uv/tools/cli-agent-orchestrator/lib" \
        -maxdepth 2 -type d -name cli_agent_orchestrator 2>/dev/null | head -1)"
fi
if [[ -z "$TARGET" || ! -d "$TARGET" ]]; then
    echo "Could not locate the installed cli_agent_orchestrator package." >&2
    exit 1
fi

INSTALLED_VERSION="$(cao --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' || echo unknown)"
CHECKOUT_VERSION="$(grep -m1 '^version' "$CHECKOUT/pyproject.toml" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' || echo unknown)"
if [[ "$INSTALLED_VERSION" != "$CHECKOUT_VERSION" ]]; then
    echo "WARNING: installed CAO is $INSTALLED_VERSION but the checkout is $CHECKOUT_VERSION." >&2
    echo "         A frontend from a different release may not match the API." >&2
fi

echo "Building web UI in $CHECKOUT/web ..."
( cd "$CHECKOUT/web" && npm install --silent && npm run build )

SRC="$CHECKOUT/src/cli_agent_orchestrator/web_ui"
[[ -d "$SRC" ]] || { echo "Build produced no $SRC" >&2; exit 1; }

# cp -R over an existing directory would nest the copy inside it, so replace
# the previous build explicitly. Only ever touches web_ui/, nothing else in
# the package.
rm -rf "${TARGET:?}/web_ui"
cp -R "$SRC" "$TARGET/web_ui"

echo "Installed web UI into $TARGET/web_ui"
echo "Restart the server, then open http://127.0.0.1:9889"
echo "  tmux kill-session -t orchestrator"
echo "  tmux new-session -d -s orchestrator 'cao-server --terminal tmux'"
