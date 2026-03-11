# Platform — Cross-Platform Path & Environment Layer

The `Platform` class (`csc_service.shared.platform`) is the single source of truth
for all CSC paths.  It detects OS, hardware, and project layout at startup and
exposes OS-correct paths via methods that work on Windows, Linux, macOS, Android, etc.

## Inheritance Position

```
Root → Log → Data → Version → Platform → Network → Service → Server
```

Platform is loaded once at startup and sets `CSC_*` env vars for the whole process.
Subprocesses and shell scripts read those env vars — or call `csc-platform` directly.

## Key Methods

| Method | Returns | Notes |
|--------|---------|-------|
| `Platform.get_etc_dir()` | `Path` | Persistent config: `PROJECT_ROOT/etc/` |
| `Platform.get_logs_dir()` | `Path` | Log files: `PROJECT_ROOT/logs/` |
| `Platform.PROJECT_ROOT` | `Path` | Project root (auto-detected) |
| `p.get_abs_tmp_path([...])` | `str` | OS tmp dir + subpath |
| `p.get_abs_etc_path([...])` | `str` | etc/ + subpath |
| `p.export_env_paths()` | — | Sets all `CSC_*` env vars |

## Environment Variables (set by `export_env_paths()`)

| Variable | Value |
|----------|-------|
| `CSC_ROOT` | Project root directory |
| `CSC_ETC` | `$CSC_ROOT/etc/` |
| `CSC_LOGS` | `$CSC_ROOT/logs/` |
| `CSC_TMP` | OS temp dir / `csc/` |
| `CSC_OPS_WO` | `$CSC_ROOT/ops/wo/` |
| `CSC_OPS_AGENTS` | `$CSC_ROOT/ops/agents/` |
| `CSC_BIN` | `$CSC_ROOT/irc/bin/` |

## `csc-platform` CLI Tool

For shell scripts that need Platform paths without a Python import:

```bash
# Linux / macOS
csc-platform get_etc_dir        # → /opt/csc/etc
csc-platform get_logs_dir       # → /opt/csc/logs
csc-platform get_root           # → /opt/csc
csc-platform get_tmp            # → /tmp/csc/run

# Load all CSC_ vars into current shell
eval $(csc-platform env)
echo $CSC_ETC                   # → /opt/csc/etc
```

```batch
:: Windows
csc-platform.bat get_etc_dir
for /f "tokens=*" %%i in ('csc-platform.bat get_etc_dir') do set CSC_ETC=%%i
```

**Script locations:**
- Linux/macOS: `irc/bin/csc-platform` (chmod +x, `#!/usr/bin/env python3`)
- Windows: `irc/bin/csc-platform.bat` (calls `python -m csc_service.shared.platform`)
- Installed entry point: `csc-platform` (via pip install)

## Data Layer Integration

`Data` (parent of Platform in the chain) uses Platform for path resolution via lazy import:

```python
def _get_etc_dir(self) -> Path:
    from csc_service.shared.platform import Platform   # lazy, avoids circular import
    return Platform.get_etc_dir()
```

This means every class in the hierarchy (`PersistentStorageManager`, `Server`, etc.)
gets OS-correct paths automatically via `self._get_etc_dir()`.

## File Layout

```
PROJECT_ROOT/
  etc/          ← persistent config (csc-service.json, platform.json, opers.json, olines.conf)
  logs/         ← all log files
  irc/          ← code submodule
  ops/          ← ops submodule (agents, workorders)
  tmp/          ← runtime state (not etc/)
```

---

# platform.json — Runtime Configuration Reference

`etc/platform.json` holds per-node runtime settings for csc-service.
The file is read by `csc_service.config.ConfigManager`.

## Top-level structure

```json
{
  "runtime": { ... }
}
```

## `runtime` section

### `wo_watcher` — ops/wo/ Filesystem Watcher

Monitors `ops/wo/` for any filesystem change and pushes changed files to the
FTP master (fahu), which replicates to all registered slave nodes.

| Key               | Type    | Default                               | Description                                                       |
|-------------------|---------|---------------------------------------|-------------------------------------------------------------------|
| `enabled`         | bool    | `false`                               | Set to `true` to start the watcher at service startup.            |
| `ftp_master_host` | string  | `"fahu.facingaddictionwithhope.com"`  | Hostname of the FTP master node.                                  |
| `ftp_master_port` | int     | `9521`                                | FTP control port (CSC uses the 9520–9529 range).                  |
| `watch_dir`       | string  | `"ops/wo"`                            | Directory to watch, relative to the project root.                 |
| `debounce_ms`     | int     | `500`                                 | Milliseconds to batch rapid changes before pushing.               |
| `poll_interval_s` | int     | `5`                                   | Polling interval (seconds) used on platforms without inotify.     |

Example:

```json
{
  "runtime": {
    "wo_watcher": {
      "enabled": false,
      "ftp_master_host": "fahu.facingaddictionwithhope.com",
      "ftp_master_port": 9521,
      "watch_dir": "ops/wo",
      "debounce_ms": 500,
      "poll_interval_s": 5
    }
  }
}
```

### csc-ctl integration

```
csc-ctl enable wo-watcher       # start watching ops/wo/ and auto-syncing
csc-ctl status wo-watcher       # show last sync time, hash, connected slaves
csc-ctl disable wo-watcher      # stop (manual git sync still works)
```

### Detection strategy (Linux → macOS → Windows)

1. **inotify** (Linux, zero overhead) — via `inotify_simple` if installed.
2. **watchdog** (macOS, cross-platform) — via the `watchdog` PyPI package.
3. **Pure polling** (all platforms, no extra deps) — `stat()` every
   `poll_interval_s` seconds using a `threading.Timer` loop.

The watcher auto-selects the best available strategy at startup using
`platform.system()`.
