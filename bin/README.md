# CSC Bin Tools

Command-line tools and utilities for CSC project management, automation, and development.

## Quick Reference

| Tool | Purpose | Docs |
|------|---------|------|
| `batch_dir.py` | Execute all workorders in directory sequentially | [batch_dir.md](batch_dir.md) |
| `batch_executor.py` | Execute Batch API requests with tool loop | [batch_executor.md](batch_executor.md) |
| `analyze_project.py` | Generate code maps and project analysis | [analyze_project.md](analyze_project.md) |
| `generate_tree.py` | Create ASCII directory tree visualization | [generate_tree.md](generate_tree.md) |
| `send_chat.py` | Send IRC messages from command line | [send_chat.md](send_chat.md) |
| `c.py` | Quick Python REPL with CSC modules | [c.md](c.md) |
| `update_bins_for_venv.py` | Update script shebangs for venv | [update_bins_for_venv.md](update_bins_for_venv.md) |

## Getting Started

### Install CSC Packages
```bash
pip install -e /c/csc/irc/packages/csc-service
```

### Run Batch Executor
```bash
python3 /c/csc/bin/batch_executor.py <batch_id>
```

### Quick Python Testing
```bash
python3 /c/csc/bin/c.py
```

### Send IRC Message
```bash
python3 /c/csc/bin/send_chat.py "#channel" "message"
```

## Common Workflows

### 1. Execute a Batch and Monitor Progress
```bash
export ANTHROPIC_API_KEY="sk-ant-api03-..."
python3 batch_executor.py msgbatch_01... 2>&1 | tee batch.log
```

### 2. Analyze Project and Update Documentation
```bash
python3 analyze_project.py
python3 generate_tree.py > /c/csc/tree.txt
```

### 3. Test IRC Connectivity
```bash
python3 send_chat.py "#test" "Testing connection"
python3 c.py -c "print(IRCMessage('JOIN #test').build())"
```

### 4. Setup New Environment
```bash
python3 -m venv venv
source venv/bin/activate
pip install -e packages/csc-service
python3 update_bins_for_venv.py --force
```

## Tool Documentation Format

Each tool has a dedicated `.md` file with:
- **Overview** - What the tool does
- **Usage** - Command syntax and examples
- **Options** - Available flags and arguments
- **Examples** - Real-world usage scenarios
- **Notes** - Important details and gotchas

## Adding New Tools

When adding a new tool:

1. Create the script in `/c/csc/bin/`
2. Make it executable: `chmod +x toolname.py`
3. Add shebang: `#!/usr/bin/env python3`
4. Create `toolname.md` documentation
5. Update this README

## Tool Development Guidelines

### Shebang
```python
#!/usr/bin/env python3
```

### Imports
```python
import sys
import argparse
import subprocess
```

### Argument Parsing
```python
parser = argparse.ArgumentParser(description="Tool description")
parser.add_argument("required_arg", help="Description")
parser.add_argument("-o", "--option", help="Optional flag")
```

### Error Handling
```python
if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
```

### Exit Codes
- `0` - Success
- `1` - General error
- `2` - Usage/argument error
- `130` - Interrupted (Ctrl+C)

## Environment Variables

Common environment variables used by tools:

- `ANTHROPIC_API_KEY` - Anthropic API key (batch_executor)
- `ANTHROPIC_API_KEY_3` - Alternative API key location
- `CSC_ROOT` - Project root directory (default: /c/csc)
- `PYTHONPATH` - Python module search path

## Logging

Tools follow consistent logging format:

```
[timestamp] [level] message
```

Levels:
- `[+]` - Success
- `[!]` - Error
- `[~]` - Status/wait
- `[>]` - Action/execution
```

## Performance Notes

### batch_executor.py
- Handles variable latency (API processing can take 2-5 minutes per batch)
- Monitor with: `tail -f batch.log`
- Check status: grep "DONE\|ERROR" batch.log

### analyze_project.py
- Full analysis: ~10-30s depending on codebase size
- Quick mode: ~2-5s
- Run before commits to keep documentation current

### generate_tree.py
- Fast: <1s for typical projects
- Use in scripts and documentation generation

## Troubleshooting

### ImportError: No module named 'csc_service'
```bash
# Install packages
pip install -e /c/csc/irc/packages/csc-service
```

### Python not found in shebang
```bash
# Update shebangs for current environment
python3 update_bins_for_venv.py --force
```

### API key errors
```bash
# Set API key
export ANTHROPIC_API_KEY="sk-ant-api03-..."

# Or use KEY_3
export ANTHROPIC_API_KEY="$(grep ANTHROPIC_API_KEY_3 /c/csc/.env | cut -d'"' -f2)"
```

## Contributing

When modifying tools:
1. Update corresponding `.md` file
2. Test with `python3 tool.py --help`
3. Add examples to documentation
4. Update this README if changing tool list

## Related Documentation

- `/c/csc/CLAUDE.md` - Project guidelines
- `/c/csc/README.md` - Main project documentation
- `/c/csc/tools/INDEX.txt` - Code API reference
