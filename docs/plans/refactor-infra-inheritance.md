# Plan: Refactor CSC Infrastructure to Inherited Log/Data Patterns

## Goal
Properly integrate the CSC `Log` and `Data` inheritance hierarchy into the background services (`queue-worker`, `pm`, `pr-review`) so they use standard platform-aware paths for logs and runtime data.

## Inheritance Hierarchy (CSC Standard)
`Root` -> `Log` -> `Data` -> `Version` -> `Platform` -> `Network` -> `Service`

## Proposed Changes

### 1. Refactor `queue_worker.py`
- Create a `QueueWorker(Data)` class.
- Move current functions into class methods.
- Replace manual file logging/JSON operations with `self.log()` and `self.put_data()` / `self.get_data()`.
- The `Data` constructor will automatically use the temp/runtime paths defined in `Platform`.

### 2. Refactor `pm.py` & `pm_executor.py`
- Ensure `PMExecutor` (which already inherits from `Data`) is the primary interface for PM state.
- Update `pm.py` to use `EXECUTOR` methods for all logging and state.
- Fix `PMExecutor` process checks (`os.kill(pid, 0)`) to work on Windows using `tasklist`.

### 3. Refactor `pr_review.py`
- Create a `PRReviewer(Data)` class (or similar).
- Inherit logging/data capabilities.
- Integrate into the `csc-service` daemon loop.

### 4. Update `main.py` (csc-service)
- Ensure `Platform` is initialized at the very start to set up the global `_platform_log_dir` in `Log`.
- Update the daemon loop to instantiate the service classes and call their `run_cycle()` methods.

## Verification Strategy
- Run `csc-ctl cycle <service>` manually to verify class instantiation and execution.
- Check `%TEMP%/csc/run/` for the generated `.log` and `_data.json` files.
- Verify `csc-service --daemon` runs all subsystems without crashing.
