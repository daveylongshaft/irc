[← Back to README](../README.md)

# Platform Detection & Cross-Platform Support

The Platform layer detects system capabilities and enables cross-platform operation of CSC across Linux, Windows, macOS, Android (Termux), WSL, and Docker containers.

---

## Architecture

The Platform class sits in the shared inheritance chain:

```
Root -> Log -> Data -> Version -> Platform -> Network -> Service
```

On initialization, it detects hardware, OS, virtualization, geography, time, software tools, Docker capability, AI agents, and resource levels. Everything is persisted to `platform.json`.

**Location**: `packages/csc_shared/platform.py`

---

## Detection Categories

### Hardware
- CPU cores, processor name, architecture
- CPU speed (MHz) - detected from Windows registry/PowerShell, Linux /proc/cpuinfo, macOS sysctl
- RAM total/available (Linux: /proc/meminfo, Windows: ctypes, macOS: sysctl)
- Disk total/free via `shutil.disk_usage`

### Operating System
- System name (Linux/Windows/Darwin)
- Release, version, Python version
- Linux distribution (from /etc/os-release)
- Android/Termux detection (TERMUX_VERSION env or /data/data/com.termux)

### Virtualization
- Docker containers (/.dockerenv, cgroup inspection)
- LXC containers
- WSL (kernel release contains "microsoft")
- VMs: VirtualBox, VMware, KVM, Hyper-V (via DMI sysfs)
- Cloud: AWS, GCP, Azure (via board vendor DMI)

### Network
- Hostname (via `socket.gethostname()`)
- IP addresses (IPv4 and IPv6) detected via:
  - `socket.gethostbyname_ex()` for primary hostname resolution
  - `socket.getaddrinfo()` for comprehensive address enumeration
  - Fallback dummy socket connection (8.8.8.8:80) to detect outgoing interface IP

### Software Tools
Detects 25+ tools with version strings:
- Core: python3, pip, git, node, npm, curl, gcc, make
- Docker: docker, docker-compose
- Package managers: apt, yum, pacman (Linux), pkg (Termux), choco (Windows), brew (macOS)

### AI Agents
- claude, gemini, coding-agent, aider, github-copilot-cli
- Detected via `shutil.which()` in PATH

### Resource Assessment
| Level | Cores | RAM | Disk |
|-------|-------|-----|------|
| high | 4+ | 8GB+ | 20GB+ |
| medium | 2+ | 4GB+ | 10GB+ |
| low | 1+ | 2GB+ | any |
| minimal | below low | | |

Also sets: `can_run_docker`, `can_run_ai_agents`

---

## Persistence

Platform data is written to `/opt/csc/platform.json` using the atomic write pattern (temp → fsync → rename). This file is refreshed on every server/client startup.

```python
# Read platform data from any module
from csc_shared.platform import Platform
data = Platform.load_platform_json()
```

---

## Capability Checking

The platform layer provides methods for checking if the current system can run a given task:

```python
platform.has_tool("git")                    # True if git is installed
platform.has_docker()                       # True if Docker daemon is running
platform.matches_platform(["windows"])      # True if on Windows
platform.has_min_ram("2GB")                 # True if >= 2GB RAM

# Combined check (used by prompt routing)
satisfied, reasons = platform.check_requirements(
    requires=["docker", "git"],
    platform_list=["linux"],
    min_ram="4GB"
)
```

---

## Prompt Capability Tags (YAML Front-Matter)

Prompt files can declare requirements using YAML front-matter:

```markdown
---
requires: [docker, git, python3]
platform: [linux, windows]
min_ram: 4GB
---
# My Task Prompt
...
```

When the agent service assigns a prompt, it checks these tags against the platform inventory. If the system doesn't meet requirements, the prompt stays in `ready/` for another machine.

---

## Cross-Platform Test Infrastructure

### Platform Gate

Tests targeting a specific platform use `tests/platform_gate.py`:

```python
from platform_gate import require_platform
require_platform(["windows"])  # Skip if not Windows

class TestWindowsSpecific(unittest.TestCase):
    ...
```

When a gated test runs on the wrong platform:
1. It prints `PLATFORM_SKIP: <reason>` to stdout
2. The cron runner (`tests/run_tests.sh`) detects this line
3. The log file **stays** — locks this machine from re-running the test
4. Cron generates a `PROMPT_run_test_<name>.md` routing prompt in `workorders/ready/`
5. The prompt flows via git to other machines
6. An AI on the right platform picks up the prompt, deletes the log there, and lets cron run the test
7. Test passes on the correct platform

### Platform-Specific Test Files

| Test File | Target Platform |
|-----------|----------------|
| `test_platform.py` | All (generic) |
| `test_platform_windows.py` | Windows |
| `test_platform_macos.py` | macOS |
| `test_platform_android.py` | Android/Termux |
| `test_platform_docker.py` | Docker container |
| `test_platform_wsl.py` | WSL |

### Per-Test Gating

For mixed-platform test files, use the decorator:

```python
from platform_gate import skip_unless_platform

class TestMixed(unittest.TestCase):
    @skip_unless_platform(["darwin"])
    def test_macos_only(self):
        ...
```

---

## Install Modes

The platform supports three install modes controlled by CLI flags:

| Flag | Behavior |
|------|----------|
| (none) | Inventory only — detect and persist, don't install anything |
| `--install-packages-at-startup` | Install missing packages when server/client starts |
| `--install-as-needed` | Install packages on demand when a prompt needs them |

```bash
csc-server --install-packages-at-startup
csc-claude --install-as-needed
```

---

## Supported Platforms

| Platform | Status | Notes |
|----------|--------|-------|
| Linux (Ubuntu/Debian) | Primary | Full support, primary development platform |
| Windows | Supported | ctypes RAM, choco detection, backslash paths |
| macOS | Supported | sysctl RAM, brew detection |
| Android (Termux) | Supported | pkg manager, mobile resource levels |
| WSL | Supported | Detected via kernel release |
| Docker | Supported | Detected via /.dockerenv and cgroup |

---

## stdlib Only

The platform layer uses **only Python standard library** — no pip dependencies:
`platform`, `os`, `sys`, `shutil`, `subprocess`, `socket`, `json`, `struct`, `time`, `pathlib`

This ensures it works on any Python 3.8+ installation, even on a fresh Termux install before any packages are added.

---

[Prev: AI Agents](ai_clients.md) | [Next: Setup & Deployment](setup.md)
