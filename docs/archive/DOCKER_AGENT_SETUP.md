# Docker Coding Agent - Setup & Verification

## Status: ✅ INSTALLED & READY

### Installation Complete
- [x] Python package installed: `coding-agent==0.1.0`
- [x] Click CLI available: `python -m coding_agent.cli`
- [x] Agents registered in agent_service.py:
  - `docker-python` - Python 3 isolated execution
  - `docker-bash` - Bash isolated execution
  - `docker-node` - Node.js 18 isolated execution

### What's Installed

```
packages/coding-agent/
├── coding_agent/
│   ├── __init__.py         (package exports)
│   ├── agent.py            (CodingAgent class - 66 lines)
│   ├── cli.py              (Click CLI - 103 lines)
│   └── docker_runner.py    (Docker subprocess wrapper - 106 lines)
├── docker/
│   ├── Dockerfile          (Python 3.11 + Node.js 18 + Bash)
│   ├── entrypoint.sh       (Multi-runtime execution script)
│   └── docker-compose.yml  (Local development)
├── tests/
│   ├── test_agent.py       (Unit tests)
│   └── test_integration.py (Docker integration tests)
├── bin/
│   └── coding-agent        (Shell wrapper)
├── setup.py                (Package definition)
└── README.md               (Complete documentation)

tests/
└── test_coding_agent.py    (CSC framework integration tests)
```

### Next Steps to Complete Setup

#### 1. Build the Docker Image
```bash
cd /c/csc/packages/coding-agent/docker
docker build -t coding-agent:latest .
```

**Required:** Docker daemon must be running (Docker Desktop on Windows)

#### 2. Create a Shell Wrapper (Optional)
The entry point is installed via pip, but you can also use:
```bash
python -m coding_agent.cli -m python3 -p "print('hello')"
```

Or if the script is in PATH:
```bash
coding-agent -m python3 -p "print('hello')"
```

#### 3. Test the Installation
```bash
# Test CLI help
python -m coding_agent.cli --help

# Test agent selection (via CSC)
AI do agent list
AI do agent select docker-python

# Test execution (once Docker image is built)
AI do agent assign PROMPT_test.md
```

### How It Works

1. **User assigns prompt** → `AI do agent assign PROMPT.md`
2. **Agent service calls** → `coding-agent -y -m python3 -p "<prompt_content>"`
3. **CLI invokes agent** → `CodingAgent.execute(script, runtime)`
4. **Agent spawns Docker** → `docker run --rm --memory 512m ... <script>`
5. **Container executes** → `/entrypoint.sh` runs script in isolated environment
6. **Result returns** → stdout/stderr captured and logged

### Docker Image Features

- **Python 3.11** - Via slim base image
- **Node.js 18** - Installed from NodeSource
- **Bash** - Native in slim image
- **Common tools** - curl, wget, git, jq
- **Security**:
  - Non-root user (uid 1000)
  - Memory limit: 512MB
  - CPU limit: 1.0 core
  - Dropped all capabilities (--cap-drop=ALL)
  - Read-only filesystem (--read-only --tmpfs /tmp)
  - Timeout: 30 seconds (configurable)

### Verification Checklist

Run this to verify setup:

```bash
# Check package installed
python -c "from coding_agent import CodingAgent; print('OK: Package installed')"

# Check CLI works
python -m coding_agent.cli --help | head -5

# Check agents registered
grep docker- /c/csc/packages/csc_shared/services/agent_service.py

# Check tests exist
ls -la tests/test_coding_agent.py

# Build Docker image (requires Docker)
docker build -t coding-agent:latest packages/coding-agent/docker/
docker images | grep coding-agent
```

### Usage Examples

#### Python
```bash
coding-agent -y -m python3 -p "
import math
print(math.sqrt(16))
"
```

#### Bash
```bash
coding-agent -y -m bash -p "
for i in 1 2 3; do
  echo "Item $i"
done
"
```

#### Node.js
```bash
coding-agent -y -m node18 -p "
console.log(new Date().toISOString())
"
```

### Troubleshooting

**"Could not pull or find Docker image"**
- Build the image: `docker build -t coding-agent:latest packages/coding-agent/docker/`
- Requires Docker daemon running

**"Docker not found. Is Docker installed and in PATH?"**
- Install Docker Desktop: https://www.docker.com/products/docker-desktop
- Start the Docker daemon

**"No module named 'click'"**
- Already installed with: `pip install -e packages/coding-agent`
- If missing: `pip install click>=8.0.0`

**Script timeout**
- Use `--timeout` flag: `coding-agent -m python3 -p "..." --timeout 60`
- Default is 30 seconds

### Files Modified

- `packages/csc_shared/services/agent_service.py`:
  - Added 3 agents to KNOWN_AGENTS dict
  - Added coding-agent command builder in _build_cmd()

### Tests for Cron

Automated tests ready for cron execution:
- `tests/test_coding_agent.py` - CSC framework integration
- `tests/test_agent.py` - Unit tests (in package)
- `tests/test_integration.py` - Docker-based functional tests

Cron will automatically run these. Check logs in `tests/logs/test_coding_agent.log`

### Git History

- Commit: `8d6bd1e` - "Add Docker-based coding agent for isolated code execution"
- Status: ✅ Pushed to remote

### References

- Package README: `packages/coding-agent/README.md`
- Setup instructions: This file
- Docker security: https://docs.docker.com/engine/security/
- Click CLI: https://click.palletsprojects.com/
