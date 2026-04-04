#!/bin/bash
set -e

echo "=== IRC Codex Environment Setup ==="

# Update system packages
echo "[1/4] Installing system dependencies..."
apt-get update
apt-get install -y \
  build-essential \
  python3-dev \
  python3-venv \
  git

# Install Python packages (editable mode)
echo "[2/4] Installing IRC packages..."
pip install --upgrade pip setuptools wheel
pip install -e packages/csc-shared
pip install -e packages/csc-server
pip install -e packages/csc-bridge
pip install -e packages/csc-cli
pip install -e packages/csc-clients

# Export environment variables
echo "[3/4] Setting environment variables..."
export IRC_HOME=$(pwd)
export IRC_ENV="codex"
export PYTHONPATH="$IRC_HOME/packages/csc-shared:$IRC_HOME/packages/csc-server:$PYTHONPATH"

# Verify setup
echo "[4/4] Verifying setup..."
python3 -c "from csc_shared.irc import IRCMessage; print('✓ IRC packages OK')"

echo ""
echo "=== Setup Complete ==="
echo "Environment variables exported:"
echo "  IRC_HOME: $IRC_HOME"
echo "  IRC_ENV: $IRC_ENV"
echo ""
echo "Ready to run:"
echo "  csc-ctl status"
