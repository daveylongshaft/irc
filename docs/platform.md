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
