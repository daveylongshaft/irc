# Layer Package Installer Integration Guide

This repo now contains a planner module for integrating the layered CSC core
packages into a future `csc-ctl` reinstall workflow without requiring this repo
to directly stop live services.

## Module

- Python module: `csc_service.installer.layer_packages`
- Purpose: generate uninstall/install order, render Windows/Linux-friendly pip
  commands, and provide import migration mappings.

## What it does

The installer helper is designed for this sequence:

1. Use the **old** control app / `csc-ctl` to stop and uninstall running
   services while preserving config and state.
2. Pull repo changes.
3. Use the **new** control app integration to install the layered packages in
   dependency order.
4. Re-enable and restart services.
5. Run site/system tests.

## Dependency order

The new package chain is installed in this order:

1. `csc-root`
2. `csc-log`
3. `csc-data`
4. `csc-version`
5. `csc-platform`
6. `csc-network`
7. `csc-service-base`
8. `csc-server-core`

And removed in the reverse order.

## Example: render a Linux plan

```bash
PYTHONPATH=packages/csc-service python -m csc_service.installer.layer_packages --shell bash
```

## Example: render a Windows / PowerShell plan

```powershell
$env:PYTHONPATH = "packages/csc-service"
python -m csc_service.installer.layer_packages --shell powershell
```

## Example: integrate into a future control command

```python
from csc_service.installer.layer_packages import build_install_commands, render_install_plan

for command in build_install_commands(python_executable="python3", shell="bash"):
    print(command)

print(render_install_plan(shell="powershell"))
```

## Import migration examples

Replace legacy imports with the layered packages:

```python
from csc_service.shared.root import Root          # old
from csc_root import Root                         # new

from csc_service.shared.log import Log            # old
from csc_log import Log                           # new

from csc_service.shared.data import Data          # old
from csc_data import Data                         # new

from csc_service.shared.version import Version    # old
from csc_version import Version                   # new

from csc_service.shared.platform import Platform  # old
from csc_platform import Platform                 # new

from csc_service.shared.network import Network    # old
from csc_network import Network                   # new

from csc_service.server.service import Service    # old
from csc_service_base import Service              # new

from csc_service.server.server import Server      # old
from csc_server_core import Server                # new
```

## Notes

- The **core inheritance chain** is now package-to-package.
- Some higher layers still use non-core helpers from `csc_service` (for example
  `ServerData`, server handlers, and shared IRC helpers). Those can be migrated
  later without changing the install planner contract.
- `resolve_repo_root()` prefers `Platform.PROJECT_ROOT` when available, but
  falls back to walking up from the current file if the full CSC runtime is not
  installed yet.


## Encrypted Data notes

- `csc-data` now expects `enc-ext-vfs`, `jsonschema`, and stores encrypted relative data files and log output in `CSC_ROOT/vfs/`.
- The previous plaintext implementation is preserved in `csc_data.old_data` so operators can switch by renaming package directories (`data` <-> `data_enc`, `old_data` <-> `data`) during rollout experiments.
- A `.csc_root` marker file is used to discover `CSC_ROOT` by walking upward from the current runtime location.
