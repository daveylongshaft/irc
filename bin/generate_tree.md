# generate_tree.py - Directory Tree Generator

Generate ASCII directory tree visualization of project structure.

## Overview

Creates visual tree representation of project directories, useful for:
- Understanding directory layout
- Documentation
- Navigation reference
- Identifying empty/unused directories

## Usage

```bash
python3 /c/csc/bin/generate_tree.py [options]

# Generate tree of current directory
python3 /c/csc/bin/generate_tree.py

# Generate tree of specific path
python3 /c/csc/bin/generate_tree.py /c/csc

# Limit depth
python3 /c/csc/bin/generate_tree.py --max-depth 2

# Include hidden files
python3 /c/csc/bin/generate_tree.py --show-hidden

# Save to file
python3 /c/csc/bin/generate_tree.py > tree.txt
```

## Command Line Options

- `<path>` - Directory to generate tree for (default: current dir)
- `--max-depth N` - Maximum directory depth (default: unlimited)
- `--show-hidden` - Include hidden files/dirs (starting with .)
- `--exclude <pattern>` - Exclude files matching pattern
- `--output <file>` - Write to file instead of stdout

## Example Output

```
/c/csc/
├── .env
├── .gitignore
├── CLAUDE.md
├── README.md
├── bin/
│   ├── analyze_project.py
│   ├── batch_executor.py
│   ├── batch_executor.md
│   └── generate_tree.py
├── irc/
│   ├── bin/
│   │   ├── analyze_project.py
│   │   ├── c.py
│   │   └── send_chat.py
│   ├── packages/
│   │   ├── csc-service/
│   │   │   ├── csc_service/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── cli/
│   │   │   │   ├── server/
│   │   │   │   └── shared/
│   │   │   └── pyproject.toml
│   │   └── csc-shared/
│   └── tests/
│       ├── test_server.py
│       └── logs/
├── ops/
│   └── wo/
│       ├── ready/
│       ├── wip/
│       └── done/
└── tools/
    ├── INDEX.txt
    └── csc-service.txt
```

## Common Patterns

### Show only first 2 levels
```bash
python3 /c/csc/bin/generate_tree.py /c/csc --max-depth 2
```

### Exclude test directories
```bash
python3 /c/csc/bin/generate_tree.py --exclude "*/test*"
```

### Generate for documentation
```bash
python3 /c/csc/bin/generate_tree.py /c/csc > docs/project_structure.txt
```

## Tree Symbols

- `├──` - Non-last item in directory
- `└──` - Last item in directory
- `│   ` - Continuation line
- `/` - Indicates directory

## Notes

- Automatically skips common unimportant directories (__pycache__, .git, node_modules)
- Files sorted alphabetically within each directory
- Directories listed before files
