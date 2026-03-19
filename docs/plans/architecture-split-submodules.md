# Architecture Plan: Decoupling csc-service Submodules

## Objective
Dismantle the `csc-service` monolith. Move all standalone system components (Server, Bridge, Client, AI Agents) into their own independent, pip-installable packages with separate process lifecycles. Retain `csc-service` strictly as the background orchestration daemon running all continuous polling loops. Ensure `csc-ctl` acts as the universal manager for all separated components across both Windows and Linux, adhering strictly to `Platform` and `Data` for configuration and paths.

## 1. Directory & Package Structure

The `/c/csc/irc/packages/` directory will be split as follows:

- **`csc-shared`**: (NEW) Base library. Contains `Platform`, `Data`, `Log`, `Root`, IRC parsing, and common utilities. All other packages depend on this.
- **`csc-service`**: (REDUCED) The orchestration daemon. Runs the polling loops: `queue-worker`, `test-runner`, `pm`, `pr-review`, `pki`, `jules`, `codex`, and `git_sync`.
- **`csc-server`**: (NEW) Standalone IRC server.
- **`csc-bridge`**: (NEW) Standalone protocol bridge.
- **`csc-client`**: (NEW) Human terminal client.
- **`csc-claude`, `csc-gemini`, `csc-chatgpt`, `csc-script-bot`**: (NEW) Independent AI client processes.
- **`csc-ctl`**: (NEW or moved to shared/service) The global CLI management tool.

## 2. Platform and Data Integrity

**Absolute Constraint:** No module may perform raw file system access (`open()`, `Path.read_text()`) for configuration or state.
- **Paths**: Must use `Platform.get_etc_dir()`, `Platform.get_logs_dir()`, `Platform.get_run_dir()`, etc.
- **Settings**: Must be stored and retrieved using the `Data` object (`get_data()`, `put_data()`).
- This ensures seamless cross-platform operation on Windows and Linux (cron / systemd).

## 3. Windows Runtime Constraints (Zero-Popup Mandate)

To ensure the computer remains usable for the owner, the following constraints are **mandatory** for the Windows implementation:

- **No Task Scheduler**: The system must **never** use Windows Task Scheduler for periodic execution. Task Scheduler is prone to focus-stealing and background window flashes.
- **No Popup Windows**: Opening any visible terminal windows, console popups, or "flash" windows is strictly prohibited.
- **Silent Services**: All background processes (`csc-service`, `csc-server`, `csc-bridge`, agents) must run as native Windows Services (using `nssm.exe` or `winsvc`) which execute in Session 0 (completely invisible).
- **Process Creation**: Any internal process spawning (via `subprocess` or similar) must use the `CREATE_NO_WINDOW` flag (0x08000000) to suppress console windows.

## 4. Component Lifecycles & `csc-ctl`

`csc-ctl` will be expanded to become the universal service manager. It must support:
`install`, `uninstall`, `enable`, `configure`, `start`, `stop`, `restart`, `status`

### Service Management Strategy:
- **Linux**: `csc-ctl` generates and manages `systemd` user/system units.
- **Windows**: `csc-ctl` generates and manages **Windows Services** (via `winsvc` / `nssm`).
- **Independent Upgrades**: Because they are separate pip packages, `pip install -U packages/csc-server` followed by `csc-ctl restart server` will not interrupt `csc-service` polling loops or `csc-bridge` connections.

## 5. Execution Phases

### Phase 1: Foundation (`csc-shared`)
1. Create `packages/csc-shared/`.
2. Migrate `csc_service.shared.*` to `csc_shared.*`.
3. Update `Platform` and `Data` to support multiple distinct consumers without lock contention on `platform.json` and `data.json`.

### Phase 2: Orchestration Isolation (`csc-service`)
1. Strip all `threading.Thread(target=srv.run)` and Bridge startup code from `csc_service/main.py`.
2. `main.py` becomes a pure polling loop runner (`pm`, `queue-worker`, `test-runner`, `pr-review`, `pki`, `jules_monitor`, `codex_monitor`, etc.).

### Phase 3: Component Extraction
1. Extract `csc_service/server` to `packages/csc-server`. Create `bin/csc-server` entry point.
2. Extract `csc_service/bridge` to `packages/csc-bridge`. Create `bin/csc-bridge` entry point.
3. Extract clients to `packages/csc-client`, `packages/csc-claude`, `packages/csc-gemini`, etc.

### Phase 4: The Controller (`csc-ctl`)
1. Refactor `csc-ctl` to iterate over the new packages.
2. Implement cross-platform `install`/`uninstall` to register these individual binaries with the host OS's service manager.
3. Implement `start`/`stop`/`restart` to command the OS service manager.

## 6. Risks & Mitigation
- **State Synchronization**: Server, Bridge, and Polling Loops must safely share the same `Data` files. Mitigation: Ensure atomic JSON writes (already in `Data._write_json_file`) and proper read-on-access properties.
- **Migration**: Existing `csc-service.json` will need to map to the new individual service configurations. Mitigation: `csc-ctl` will parse the legacy config and distribute the settings via the `Data` object to the respective new domains.
