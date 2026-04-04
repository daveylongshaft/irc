#!/bin/bash
set -e

echo "=== IRC Codex Maintenance (Cache Resume) ==="

# Reinstall packages (in case dependencies changed)
echo "[1/2] Reinstalling IRC packages..."
pip install --upgrade pip setuptools wheel
pip install -e packages/csc-shared
pip install -e packages/csc-server
pip install -e packages/csc-bridge
pip install -e packages/csc-cli
pip install -e packages/csc-clients

# Validate environment
echo "[2/2] Validating environment..."
export IRC_HOME=$(pwd)
export IRC_ENV="codex"
export PYTHONPATH="$IRC_HOME/packages/csc-shared:$IRC_HOME/packages/csc-server:$PYTHONPATH"

python3 -c "from csc_shared.irc import IRCMessage; print('✓ Ready')"

echo ""
echo "=== Maintenance Complete ==="
echo "Cache resumed. Ready for agent work."
