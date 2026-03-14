# Platform-Agnostic Path Resolution

## Overview

All paths in the CSC system now resolve dynamically at runtime, supporting Windows, Linux, and macOS without code changes.

## Path Resolution Strategy

### Priority Order

1. **Environment Variable**: `CSC_ROOT` (if set)
2. **Script Detection**: Parent directory of running script/module (for bin/ scripts)
3. **Directory Detection**: Check if `irc/` and `ops/` exist in current directory
4. **Parent Detection**: Check if they exist in parent directory
5. **Fallback**: Current working directory

### Python Code (Pathlib)

```python
# All Python modules use Path.resolve() for platform independence
from pathlib import Path

# Get module location
module_path = Path(__file__).resolve()

# Calculate project root by walking up directory tree
for _ in range(10):
    if (current / "CLAUDE.md").exists() or (current / "csc-service.json").exists():
        return current  # Found root
    current = current.parent
```

This automatically works on:
- **Windows**: `/c/csc` (Cygwin) or `C:\csc` (native)
- **Linux**: `~/csc` (recommended) or any path
- **macOS**: Any path

### Environment Variable

Set `CSC_ROOT` to override detection:

```bash
# Windows
set CSC_ROOT=C:\csc
# or Cygwin
export CSC_ROOT=/c/csc

# Linux
export CSC_ROOT=/csc

# macOS
export CSC_ROOT=/path/to/csc
```

### Python Script Detection (bin/ tools)

```python
import os
from pathlib import Path

# Detection logic (used in batch_executor.py, etc.)
_csc_env = os.environ.get("CSC_ROOT")
if _csc_env:
    CSC_ROOT = Path(_csc_env)
else:
    cwd = Path.cwd()
    if (cwd / "irc").exists() and (cwd / "ops").exists():
        CSC_ROOT = cwd
    elif (cwd.parent / "irc").exists() and (cwd.parent / "ops").exists():
        CSC_ROOT = cwd.parent
    else:
        CSC_ROOT = cwd
```

### Batch Script Detection (bin/ .bat and .sh)

**Windows (batch)**:
```batch
if defined CSC_ROOT (
    set CSC_PATH=%CSC_ROOT%
) else (
    REM Use script directory parent (bin/.. = csc root)
    for %%I in ("%~dp0..") do set CSC_PATH=%%~fI
)
```

**Linux/macOS (shell)**:
```bash
if [ -n "$CSC_ROOT" ]; then
    CSC_PATH="$CSC_ROOT"
else
    # Use script directory parent
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    CSC_PATH="$(dirname "$SCRIPT_DIR")"
fi
```

## Directory Structure Expectations

Regardless of the root path, the structure is:

```
CSC_ROOT/
├── irc/
│   ├── packages/
│   │   └── csc-service/
│   ├── deploy/
│   └── bin/
├── ops/
│   ├── agents/
│   ├── wo/
│   │   ├── ready/
│   │   ├── wip/
│   │   ├── done/
│   │   └── archive/
│   ├── prompts/
│   └── ...
├── bin/
│   ├── batch_executor.py
│   ├── claude-auto-resume.bat
│   ├── claude-auto-resume.sh
│   └── ...
├── logs/
├── docs/
├── CLAUDE.md
├── csc-service.json
└── ...
```

## Path Normalization

### No Hardcoded Paths

❌ **Bad** (hardcoded):
```python
path = Path("/c/csc/ops/wo")
```

✅ **Good** (dynamic):
```python
path = PROJECT_ROOT / "ops" / "wo"
```

### Cygwin Path Conversion

For tools that need Windows native paths (legacy tools, Windows APIs):

```python
def normalize_path(path: str) -> str:
    """Convert /c/... to C:\..., with fallback if cygpath unavailable."""
    if path.startswith("/c/"):
        try:
            result = subprocess.run(["cygpath", "-w", path], ...)
            if result.returncode == 0:
                return result.stdout.strip()
        except:
            pass
    return path  # Return as-is on Linux or if cygpath fails
```

## Linux Migration

### Setup

1. Clone to `~/csc` (no root required):
   ```bash
   git clone --recursive <repo> ~/csc
   cd ~/csc
   ```

   Alternatively, clone anywhere and set `CSC_ROOT`:
   ```bash
   git clone --recursive <repo> /any/path/csc
   export CSC_ROOT=/any/path/csc
   ```

2. Install packages:
   ```bash
   pip install -e irc/packages/csc-service
   ```

3. Run with auto-detection:
   ```bash
   python irc/packages/csc-service/csc_service/server/main.py --daemon
   ```

### Path Resolution Works Automatically

The detection logic will:
1. Check `CSC_ROOT` env var → if set, use it
2. Walk up from CWD looking for `.csc_root` marker → found! Use that dir as root
3. All paths resolve relative to the detected root

## Windows Migration

### Setup

On Windows (native or Cygwin):

1. Clone to `C:\csc` or `/c/csc`:
   ```cmd
   git clone --recursive <repo> C:\csc
   cd C:\csc
   ```

2. Or with Cygwin:
   ```bash
   git clone --recursive <repo> /c/csc
   cd /c/csc
   ```

3. Set environment variable (optional):
   ```cmd
   set CSC_ROOT=C:\csc
   ```

4. Install packages:
   ```cmd
   pip install -e irc/packages/csc-service
   ```

## macOS Migration

Same as Linux. Clone to `/csc` or any path, set `CSC_ROOT` if not using standard location.

## Testing Path Resolution

```bash
# Verify CSC_ROOT is detected correctly
python -c "
from pathlib import Path
import os
csc_env = os.environ.get('CSC_ROOT')
cwd = Path.cwd()
print(f'CSC_ROOT env: {csc_env}')
print(f'Current dir: {cwd}')
print(f'Has irc/: {(cwd / \"irc\").exists()}')
print(f'Has ops/: {(cwd / \"ops\").exists()}')
"
```

## Common Issues

**Problem**: "irc/ not found" or "ops/ not found"
- **Cause**: Running from wrong directory or `CSC_ROOT` not set
- **Fix**: `cd /csc` or `export CSC_ROOT=/csc`

**Problem**: Cygwin paths not converting
- **Cause**: cygpath not available (Linux)
- **Fix**: Not a problem - code has fallback, uses paths as-is

**Problem**: Permissions denied on paths
- **Cause**: Path resolution found wrong directory
- **Fix**: Explicitly set `export CSC_ROOT=/correct/path`

## Future: Docker

For Docker containerization:
```dockerfile
# Mount CSC at /csc
VOLUME ["/csc"]
ENV CSC_ROOT=/csc
```

Code automatically uses `/csc` without any changes.
