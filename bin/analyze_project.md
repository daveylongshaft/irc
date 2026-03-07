# analyze_project.py - Project Analysis Tool

Generate comprehensive codebase analysis reports including code maps, file listings, and undocumented items audit.

## Overview

Scans project directories to create:
- Code API maps (classes, methods, function signatures)
- Directory tree structure
- Flat file listings for discovery
- Analysis of undocumented code items

Used to maintain up-to-date reference documentation for code navigation.

## Usage

```bash
python3 /c/csc/bin/analyze_project.py [options]

# Analyze entire project
python3 /c/csc/bin/analyze_project.py

# Analyze specific directory
python3 /c/csc/bin/analyze_project.py --path /c/csc/irc/packages

# Quick mode (skip detailed analysis)
python3 /c/csc/bin/analyze_project.py --quick

# Generate specific outputs only
python3 /c/csc/bin/analyze_project.py --maps-only
python3 /c/csc/bin/analyze_project.py --tree-only
```

## Output Files

Generated in project root:

- `tools/INDEX.txt` - Master index of all code maps
- `tools/csc-server.txt` - csc-server package API map
- `tools/csc-shared.txt` - csc-shared package API map
- `tools/csc-service.txt` - csc-service package API map
- `tree.txt` - ASCII directory tree
- `p-files.list` - Flat list of all Python files
- `analysis_report.json` - Undocumented items audit

## Command Line Options

- `--path <dir>` - Root directory to analyze (default: current dir)
- `--quick` - Skip deep analysis, faster run
- `--maps-only` - Generate only code maps
- `--tree-only` - Generate only tree.txt
- `--output-dir <dir>` - Where to write results

## Example Output

### Code Map (tools/csc-server.txt)
```
ServerMessageHandler
  handle_privmsg(client_addr, nick, target, message_text)
    -> Handles PRIVMSG IRC commands
    -> Returns: None

  handle_join(client_addr, nick, channels)
    -> Handles JOIN IRC commands
    -> Returns: dict with status
```

### Tree (tree.txt)
```
/c/csc/
├── bin/
│   ├── analyze_project.py
│   ├── batch_executor.py
│   └── generate_tree.py
├── irc/
│   ├── packages/
│   │   ├── csc-shared/
│   │   ├── csc-server/
│   │   └── csc-service/
│   ├── bin/
│   └── tests/
├── ops/
│   └── wo/
└── tools/
    ├── INDEX.txt
    └── csc-service.txt
```

### File List (p-files.list)
```
/c/csc/irc/packages/csc-server/csc_server/main.py
/c/csc/irc/packages/csc-server/csc_server/server.py
/c/csc/irc/packages/csc-server/csc_server/storage.py
...
```

## Integration

Run before each commit to keep references current:

```bash
# Quick refresh (fastest)
python3 /c/csc/bin/analyze_project.py --quick

# Full refresh
python3 /c/csc/bin/analyze_project.py
```

Used by:
- `refresh-maps` bash command
- Pre-commit hooks
- Documentation generation

## Notes

- Scans .py files only
- Extracts classes, functions, methods
- Documents function signatures and docstrings
- Reports items without documentation
- Ignores __pycache__ and .git directories
