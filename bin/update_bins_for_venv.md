# update_bins_for_venv.py - Virtual Environment Setup

Update shebang lines in bin scripts to point to current Python virtual environment.

## Overview

When moving projects between systems or virtual environments, Python bin scripts need updated shebang lines to point to the correct Python interpreter.

This tool automatically updates all scripts in a bin directory to use the current venv's Python.

## Usage

```bash
# Update current directory's bin
python3 /c/csc/bin/update_bins_for_venv.py

# Update specific directory
python3 /c/csc/bin/update_bins_for_venv.py /c/csc/irc/bin

# Dry run (show changes without applying)
python3 /c/csc/bin/update_bins_for_venv.py --dry-run

# Force update even if shebang exists
python3 /c/csc/bin/update_bins_for_venv.py --force
```

## Command Line Options

- `<path>` - Directory containing scripts (default: ./bin)
- `--dry-run` - Preview changes without modifying files
- `--force` - Overwrite existing shebangs
- `--python <path>` - Custom Python path (default: current interpreter)
- `--verbose` - Show detailed output

## What It Does

Transforms script shebangs:

Before:
```bash
#!/usr/bin/env python3
#!/usr/bin/python
#!/usr/bin/python3.8
```

After:
```bash
#!/c/Users/davey/AppData/Local/Microsoft/WindowsApps/python3
```

(Points to current venv's Python interpreter)

## Examples

### Update bin directory after venv activation
```bash
source venv/bin/activate
python3 /c/csc/bin/update_bins_for_venv.py ./bin
```

### Dry run to see what would change
```bash
python3 /c/csc/bin/update_bins_for_venv.py --dry-run
```

### Force update all scripts
```bash
python3 /c/csc/bin/update_bins_for_venv.py --force
```

### Update irc/bin scripts
```bash
python3 /c/csc/bin/update_bins_for_venv.py /c/csc/irc/bin
```

## Output

```
Updating shebangs in /c/csc/irc/bin/

Processing: analyze_project.py
  Old: #!/usr/bin/env python3
  New: #!/c/Users/davey/AppData/Local/Microsoft/WindowsApps/python3

Processing: send_chat.py
  Old: #!/usr/bin/python3
  New: #!/c/Users/davey/AppData/Local/Microsoft/WindowsApps/python3

Processing: c.py
  Old: (no shebang)
  New: #!/c/Users/davey/AppData/Local/Microsoft/WindowsApps/python3

Updated 3 scripts
```

## Script Requirements

Scripts should be executable:

```bash
# Make scripts executable first
chmod +x /c/csc/irc/bin/*.py

# Then update shebangs
python3 /c/csc/bin/update_bins_for_venv.py /c/csc/irc/bin
```

## Why This Matters

Without correct shebangs:
- Direct execution fails: `./send_chat.py` won't work
- Wrong Python interpreter used (system python vs venv)
- Module imports fail (venv packages not available)
- Scripts fail silently or with confusing errors

## Integration

Use in deployment/setup scripts:

```bash
#!/bin/bash
set -e

# Create venv
python3 -m venv venv
source venv/bin/activate

# Install packages
pip install -e packages/csc-service

# Update bin scripts
python3 bin/update_bins_for_venv.py --force

echo "Setup complete!"
```

## Notes

- Only modifies Python scripts (.py extension)
- Skips files without execute permission
- Preserves other shebang lines unchanged
- Creates backup of original files (optional)
- Returns 0 on success, 1 on failure
