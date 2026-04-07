# Configuration Files

## Overview
Configuration files and runtime data are **NOT** tracked in git for security and to avoid conflicts. You must create them from the example templates.

## Required Configuration Files

### 1. Secret Keys (`/opt/csc/server/secret.py`)
**Template:** `server/secret.py.example`

Copy and configure:
```bash
cp server/secret.py.example server/secret.py
# Edit server/secret.py with your actual API keys
```

Contains:
- Gemini API key
- Claude/Anthropic API key
- IRC operator credentials

### 2. Claude Config (`/opt/csc/claude/claude_config.json`)
**Template:** `claude/claude_config.json.example`

Copy and configure:
```bash
cp claude/claude_config.json.example claude/claude_config.json
```

### 3. Server Runtime Data (`/opt/csc/server/Server_data.json`)
**Template:** `server/Server_data.json.example`

This file is created automatically by the server on first run, but you can initialize it:
```bash
cp server/Server_data.json.example server/Server_data.json
```

## File Ownership

Services run as `csc_user:csc_group`, so runtime config/data files should be owned by that user:

```bash
sudo chown csc_user:csc_group claude/claude_config.json
sudo chown csc_user:csc_group server/Server_data.json
sudo chown csc_user:csc_group server/secret.py
```

Or use symlinks to a shared location:
```bash
ln -s /opt/csc/shared/secret.py /opt/csc/server/secret.py
```

## Security Notes

- **NEVER** commit actual secret.py files to git
- Keep API keys secure and rotate them periodically
- .gitignore is configured to prevent accidental commits of:
  - `*_config.json` and `*.config.json`
  - `secret.py`
  - `Server_data.json`
  - `*.log` files

## Gitignore Patterns

The `.gitignore` file prevents these patterns from being tracked:
- Config files: `*_config.json`, `*.config.json`
- Secrets: `secret.py`, `**/secret.py`
- Runtime data: `Server_data.json`
- Logs: `*.log`, `logs/`

This ensures git operations work smoothly regardless of file permissions.
