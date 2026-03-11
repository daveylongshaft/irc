"""
Platform detection layer for the CSC shared package.

Detects and persists system capabilities: hardware, OS, virtualization,
geography, time, software tools, Docker capability, AI agents, and
resource assessment. Persists inventory to platform.json.

Module Overview:
    This module defines the Platform class, inserted into the inheritance
    hierarchy between Version and Network:
    Root -> Log -> Data -> Version -> Platform -> Network -> Service

Install Modes (controlled by CLI flags, default is inventory-only):
    - No flags (default): Detect what's installed, persist to platform.json.
    - --install-packages-at-startup: Install missing packages on startup.
    - --install-as-needed / -as-needed: Install on demand when a prompt needs it.

Cross-platform: stdlib only (platform, os, sys, shutil, subprocess, socket, json).
Must work on Linux, Windows, and Android (Termux).

Classes:
    Platform: Extends Version, adds system capability detection and persistence.
"""

import json
import os
import os as _os
import sys as _sys

class _platform:
    """Thin shim replacing stdlib platform module to avoid name collision."""
    @staticmethod
    def machine():
        return _os.uname().machine
    @staticmethod
    def processor():
        return _os.uname().machine
    @staticmethod
    def system():
        return _os.uname().sysname
    @staticmethod
    def release():
        return _os.uname().release
    @staticmethod
    def version():
        return _os.uname().version
    @staticmethod
    def python_version():
        return '%d.%d.%d' % _sys.version_info[:3]
import shutil
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path
from csc_service.shared.version import Version


# Parse human-readable sizes like "2GB" -> bytes
def _parse_size(size_str):
    """Parse a human-readable size string to bytes."""
    size_str = size_str.strip().upper()
    multipliers = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}
    for suffix, mult in sorted(multipliers.items(), key=lambda x: -len(x[0])):
        if size_str.endswith(suffix):
            try:
                return int(float(size_str[:-len(suffix)].strip()) * mult)
            except ValueError:
                return 0
    try:
        return int(size_str)
    except ValueError:
        return 0


class Platform(Version):
    """
    Extends Version with system capability detection and persistence.

    Root -> Log -> Data -> Version -> Platform -> Network -> Service

    On initialization, detects hardware, OS, software tools, Docker
    capability, AI agents, and persists everything to platform.json.
    """

    # Default platform.json location (next to the running process)
    PLATFORM_JSON_FILENAME = "platform.json"
    # Walk up to find project root — prefer csc-service.json (true root) over CLAUDE.md (submodule)
    _p = Path(__file__).resolve().parent
    _claude_md_stop = None
    for _i in range(10):
        if (_p / "csc-service.json").exists():
            break
        if (_p / "CLAUDE.md").exists() and _claude_md_stop is None:
            _claude_md_stop = _p  # remember but keep walking for csc-service.json
        if _p == _p.parent:
            _p = _claude_md_stop or _p
            break
        _p = _p.parent
    PROJECT_ROOT = _p

    def __init__(self):
        super().__init__()
        self.name = "platform"

        # Install mode flags (set by entry points before constructing)
        self._install_at_startup = False
        self._install_as_needed = False

        # Platform data dict — populated by detect()
        self.platform_data = {}

        # Detect and persist on init
        self._detect_all()
        self._persist_platform()

        # Export paths to environment for use by scripts and subprocess calls
        self.export_env_paths()

        # Configure logging directory using the exact platform data just detected
        from csc_service.shared.log import Log
        temp_dir = self.platform_data.get("runtime", {}).get(
            f"temp_dir_{'windows' if sys.platform == 'win32' else 'linux'}"
        )
        if temp_dir:
            Log.set_platform_log_dir(temp_dir)

        # Install background services if flag is active
        if self._install_at_startup:
            self._install_background_services()

    def configure_install_mode(self, install_at_startup=False, install_as_needed=False):
        """Configure install mode after construction (called by entry points)."""
        self._install_at_startup = install_at_startup
        self._install_as_needed = install_as_needed
        if install_at_startup:
            self.log("[Platform] Install mode: install-packages-at-startup")
        elif install_as_needed:
            self.log("[Platform] Install mode: install-as-needed")

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    def _detect_all(self):
        """Run all detection routines and populate self.platform_data."""
        self.platform_data = {
            "detected_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "working_dir": str(self.PROJECT_ROOT),
            "path_separator": os.sep,
            "hardware": self._detect_hardware(),
            "os": self._detect_os(),
            "virtualization": self._detect_virtualization(),
            "geography": self._detect_geography(),
            "time": self._detect_time(),
            "network": self._detect_network(),
            "software": self._detect_software(),
            "docker": self._detect_docker(),
            "ai_agents": self._detect_ai_agents(),
            "resource_assessment": self._assess_resources(),
            "runtime": self._detect_runtime(),
        }

    def _detect_hardware(self):
        """Detect CPU, RAM, disk, architecture."""
        info = {
            "architecture": _platform.machine(),
            "processor": _platform.processor() or "unknown",
            "cpu_cores": os.cpu_count() or 0,
            "cpu_speed_mhz": self._detect_cpu_speed(),
        }

        # RAM detection
        try:
            if sys.platform == "linux":
                with open("/proc/meminfo", "r") as f:
                    for line in f:
                        if line.startswith("MemTotal:"):
                            kb = int(line.split()[1])
                            info["ram_total_mb"] = kb // 1024
                        elif line.startswith("MemAvailable:"):
                            kb = int(line.split()[1])
                            info["ram_available_mb"] = kb // 1024
            elif sys.platform == "win32":
                import ctypes
                kernel32 = ctypes.windll.kernel32
                c_ulong = ctypes.c_ulong
                class MEMORYSTATUS(ctypes.Structure):
                    _fields_ = [
                        ("dwLength", c_ulong),
                        ("dwMemoryLoad", c_ulong),
                        ("dwTotalPhys", c_ulong),
                        ("dwAvailPhys", c_ulong),
                        ("dwTotalPageFile", c_ulong),
                        ("dwAvailPageFile", c_ulong),
                        ("dwTotalVirtual", c_ulong),
                        ("dwAvailVirtual", c_ulong),
                    ]
                mem = MEMORYSTATUS()
                mem.dwLength = ctypes.sizeof(MEMORYSTATUS)
                kernel32.GlobalMemoryStatus(ctypes.byref(mem))
                info["ram_total_mb"] = mem.dwTotalPhys // (1024 * 1024)
                info["ram_available_mb"] = mem.dwAvailPhys // (1024 * 1024)
            elif sys.platform == "darwin":
                result = subprocess.run(
                    ["sysctl", "-n", "hw.memsize"],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    info["ram_total_mb"] = int(result.stdout.strip()) // (1024 * 1024)
        except Exception:
            pass

        # Disk detection
        try:
            usage = shutil.disk_usage("/")
            info["disk_total_gb"] = round(usage.total / (1024**3), 1)
            info["disk_free_gb"] = round(usage.free / (1024**3), 1)
        except Exception:
            pass

        return info

    def _detect_cpu_speed(self):
        """Detect current/max CPU speed in MHz."""
        try:
            if sys.platform == "linux":
                # Try /proc/cpuinfo first
                if os.path.exists("/proc/cpuinfo"):
                    with open("/proc/cpuinfo", "r") as f:
                        for line in f:
                            if "cpu MHz" in line:
                                return int(float(line.split(":")[1].strip()))
                # Fallback to scaling_cur_freq
                freq_path = "/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq"
                if os.path.exists(freq_path):
                    with open(freq_path, "r") as f:
                        return int(f.read().strip()) // 1000

            elif sys.platform == "win32":
                # Use powershell for CPU speed (wmic is deprecated)
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_Processor).MaxClockSpeed"],
                    capture_output=True, text=True, timeout=10
                )
                if result.returncode == 0 and result.stdout.strip():
                    return int(result.stdout.strip())
                
                # Fallback to registry
                try:
                    import winreg
                    key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
                    speed, _ = winreg.QueryValueEx(key, "~MHz")
                    return int(speed)
                except Exception:
                    pass

            elif sys.platform == "darwin":
                result = subprocess.run(
                    ["sysctl", "-n", "hw.cpufrequency"],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    return int(result.stdout.strip()) // 1000000
        except Exception:
            pass
        return None

    def _detect_os(self):

        """Detect OS type, version, distribution."""
        info = {
            "system": _platform.system(),
            "release": _platform.release(),
            "version": _platform.version(),
            "platform": sys.platform,
            "python_version": _platform.python_version(),
        }

        # Detect Linux distribution
        if sys.platform == "linux":
            try:
                # Check for Termux (Android)
                if "TERMUX_VERSION" in os.environ or os.path.exists("/data/data/com.termux"):
                    info["distribution"] = "android-termux"
                    info["is_android"] = True
                elif os.path.exists("/etc/os-release"):
                    with open("/etc/os-release", "r") as f:
                        for line in f:
                            if line.startswith("PRETTY_NAME="):
                                info["distribution"] = line.split("=", 1)[1].strip().strip('"')
                                break
            except Exception:
                pass

        return info

    def _detect_virtualization(self):
        """Detect if running in a VM, container, WSL, or cloud."""
        info = {"type": "bare_metal"}

        try:
            if sys.platform == "linux":
                # Check for Docker container
                if os.path.exists("/.dockerenv"):
                    info["type"] = "docker_container"
                    return info

                # Check cgroup for container
                try:
                    with open("/proc/1/cgroup", "r") as f:
                        cgroup = f.read()
                        if "docker" in cgroup or "containerd" in cgroup:
                            info["type"] = "docker_container"
                            return info
                        if "lxc" in cgroup:
                            info["type"] = "lxc_container"
                            return info
                except (OSError, PermissionError):
                    pass

                # Check for WSL
                uname = _platform.release().lower()
                if "microsoft" in uname or "wsl" in uname:
                    info["type"] = "wsl"
                    return info

                # Check for VM via DMI (requires root or readable sysfs)
                try:
                    with open("/sys/class/dmi/id/product_name", "r") as f:
                        product = f.read().strip().lower()
                        if "virtualbox" in product:
                            info["type"] = "virtualbox"
                        elif "vmware" in product:
                            info["type"] = "vmware"
                        elif "kvm" in product or "qemu" in product:
                            info["type"] = "kvm"
                        elif "hyper-v" in product:
                            info["type"] = "hyper-v"
                except (OSError, PermissionError):
                    pass

                # Check for cloud providers via DMI
                try:
                    with open("/sys/class/dmi/id/board_vendor", "r") as f:
                        vendor = f.read().strip().lower()
                        if "amazon" in vendor:
                            info["cloud"] = "aws"
                        elif "google" in vendor:
                            info["cloud"] = "gcp"
                        elif "microsoft" in vendor:
                            info["cloud"] = "azure"
                except (OSError, PermissionError):
                    pass

        except Exception:
            pass

        return info

    def _detect_geography(self):
        """Detect timezone and locale-based geography."""
        info = {}
        try:
            info["timezone"] = time.strftime("%Z")
            info["utc_offset"] = time.strftime("%z")
        except Exception:
            pass

        try:
            import locale
            loc = locale.getdefaultlocale()
            if loc and loc[0]:
                info["locale"] = loc[0]
                # Extract country from locale (e.g., en_US -> US)
                parts = loc[0].split("_")
                if len(parts) >= 2:
                    info["country_code"] = parts[1][:2].upper()
        except Exception:
            pass

        return info

    def _detect_time(self):
        """Check system time accuracy."""
        info = {
            "system_time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "ntp_synced": None,
            "clock_warning": None,
        }

        try:
            if sys.platform == "linux":
                result = subprocess.run(
                    ["timedatectl", "show", "--property=NTPSynchronized", "--value"],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    synced = result.stdout.strip().lower()
                    info["ntp_synced"] = synced == "yes"
                    if not info["ntp_synced"]:
                        info["clock_warning"] = "System clock may not be synchronized with NTP"
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        return info

    def _detect_network(self):
        """Detect hostname and IP addresses."""
        info = {
            "hostname": socket.gethostname(),
            "ips": []
        }
        
        try:
            # Get all IP addresses associated with this host
            # socket.gethostbyname_ex returns (hostname, aliases, ip_list)
            try:
                _, _, ip_list = socket.gethostbyname_ex(info["hostname"])
                for ip in ip_list:
                    if ip not in info["ips"]:
                        info["ips"].append(ip)
            except Exception:
                pass
            
            # Use getaddrinfo for more comprehensive detection (including IPv6 if needed)
            try:
                addr_info = socket.getaddrinfo(info["hostname"], None)
                for addr in addr_info:
                    ip = addr[4][0]
                    if ip not in info["ips"]:
                        info["ips"].append(ip)
            except Exception:
                pass
                
            # If still empty or only localhost, try connecting to a dummy address to see outgoing interface
            if not info["ips"] or info["ips"] == ["127.0.0.1"]:
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    # Doesn't actually connect, just finds the interface
                    s.connect(("8.8.8.8", 80))
                    local_ip = s.getsockname()[0]
                    if local_ip not in info["ips"]:
                        info["ips"].append(local_ip)
                    s.close()
                except Exception:
                    pass
        except Exception:
            pass
            
        return info

    def _run_version_cmd(self, binary, args=None):
        """Run a command and return version string or None."""
        cmd = [binary] + (args or ["--version"])
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                output = result.stdout.strip() or result.stderr.strip()
                # Return first non-empty line
                for line in output.split("\n"):
                    line = line.strip()
                    if line:
                        return line
            return None
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return None

    def _detect_software(self):
        """Detect installed software tools and their versions."""
        tools = {}

        checks = {
            "python3": (["python3", "--version"], None),
            "python": (["python", "--version"], None),
            "pip": (["pip", "--version"], None),
            "pip3": (["pip3", "--version"], None),
            "git": (["git", "--version"], None),
            "node": (["node", "--version"], None),
            "npm": (["npm", "--version"], None),
            "curl": (["curl", "--version"], None),
            "gcc": (["gcc", "--version"], None),
            "make": (["make", "--version"], None),
            "docker": (["docker", "--version"], None),
            "docker-compose": (["docker-compose", "--version"], None),
        }

        # Package managers
        if sys.platform == "linux":
            checks["apt"] = (["apt", "--version"], None)
            checks["yum"] = (["yum", "--version"], None)
            checks["pacman"] = (["pacman", "--version"], None)
            checks["pkg"] = (["pkg", "--version"], None)  # Termux
        elif sys.platform == "win32":
            checks["choco"] = (["choco", "--version"], None)
        elif sys.platform == "darwin":
            checks["brew"] = (["brew", "--version"], None)

        for name, (cmd, _) in checks.items():
            try:
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=10
                )
                if result.returncode == 0:
                    output = (result.stdout.strip() or result.stderr.strip())
                    version_line = ""
                    for line in output.split("\n"):
                        if line.strip():
                            version_line = line.strip()
                            break
                    tools[name] = {"installed": True, "version": version_line}
                else:
                    tools[name] = {"installed": False}
            except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
                tools[name] = {"installed": False}

        return tools

    def _detect_docker(self):
        """Detect Docker availability, daemon status, and resources."""
        info = {
            "installed": False,
            "daemon_running": False,
            "version": None,
            "usable": False,
        }

        # Check if docker binary exists
        if not shutil.which("docker"):
            return info

        info["installed"] = True

        # Get version
        try:
            result = subprocess.run(
                ["docker", "--version"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                info["version"] = result.stdout.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        # Check daemon
        try:
            result = subprocess.run(
                ["docker", "ps"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                info["daemon_running"] = True
                info["usable"] = True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        # Get Docker system info if daemon is running
        if info["daemon_running"]:
            try:
                result = subprocess.run(
                    ["docker", "info", "--format", "{{json .}}"],
                    capture_output=True, text=True, timeout=15
                )
                if result.returncode == 0:
                    try:
                        docker_info = json.loads(result.stdout)
                        info["containers_running"] = docker_info.get("ContainersRunning", 0)
                        info["images"] = docker_info.get("Images", 0)
                        mem_bytes = docker_info.get("MemTotal", 0)
                        if mem_bytes:
                            info["memory_mb"] = mem_bytes // (1024 * 1024)
                    except json.JSONDecodeError:
                        pass
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass

        return info

    def _detect_ai_agents(self):
        """Detect which AI CLI tools are available in PATH."""
        agents = {}
        agent_binaries = {
            "claude": "claude",
            "gemini": "gemini",
            "coding-agent": "coding-agent",
            "aider": "aider",
            "copilot": "github-copilot-cli",
        }

        for name, binary in agent_binaries.items():
            path = shutil.which(binary)
            agents[name] = {
                "installed": path is not None,
                "path": path,
            }

        return agents

    def _assess_resources(self):
        """Assess whether this box can handle Docker + AI workloads."""
        assessment = {
            "can_run_docker": False,
            "can_run_ai_agents": False,
            "resource_level": "minimal",
        }

        hw = self.platform_data.get("hardware", {})
        docker = self.platform_data.get("docker", {})
        agents = self.platform_data.get("ai_agents", {})

        cores = hw.get("cpu_cores", 0)
        ram_mb = hw.get("ram_total_mb", 0)
        disk_gb = hw.get("disk_free_gb", 0)

        # Docker assessment
        if docker.get("usable"):
            assessment["can_run_docker"] = True

        # AI agent assessment
        any_agent = any(a.get("installed") for a in agents.values())
        if any_agent and ram_mb >= 1024:
            assessment["can_run_ai_agents"] = True

        # Resource level
        if cores >= 4 and ram_mb >= 8192 and disk_gb >= 20:
            assessment["resource_level"] = "high"
        elif cores >= 2 and ram_mb >= 4096 and disk_gb >= 10:
            assessment["resource_level"] = "medium"
        elif cores >= 1 and ram_mb >= 2048:
            assessment["resource_level"] = "low"
        else:
            assessment["resource_level"] = "minimal"

        return assessment

    def _detect_runtime(self):
        """Detect runtime directories (temp root, agent work base) in both Windows and Linux notations."""
        runtime = {}

        # Helper function to convert between Windows and Linux/WSL path notations
        def convert_to_linux_notation(win_path):
            """Convert Windows path to /mnt/X/... notation."""
            win_path = str(win_path).replace("/", "\\")  # Normalize to backslashes
            if len(win_path) >= 2 and win_path[1] == ":":
                drive_letter = win_path[0].lower()
                rest = win_path[2:].replace("\\", "/")
                return f"/mnt/{drive_letter}{rest}"
            return str(win_path).replace("\\", "/")

        def convert_to_windows_notation(linux_path):
            """Convert /mnt/X/... notation to Windows path."""
            linux_path = str(linux_path).replace("\\", "/")  # Normalize to forward slashes
            if linux_path.startswith("/mnt/"):
                # /mnt/c/Users/... -> C:\Users\...
                parts = linux_path.split("/")
                if len(parts) >= 3:
                    drive_letter = parts[2].upper()
                    rest = "\\".join(parts[3:])
                    if rest:
                        return f"{drive_letter}:\\{rest}"
                    else:
                        return f"{drive_letter}:\\"
            return linux_path.replace("/", "\\")

        # CSC temp directory is inside project root for portability
        try:
            temp_root = Path(self.get_abs_tmp_path([]))

            # Get the actual temp path as string
            temp_str = str(temp_root)

            # Determine which notation we currently have and compute both
            if sys.platform == "win32" or (len(temp_str) >= 3 and temp_str[1:3] == ":\\"):
                # Currently in Windows notation
                temp_windows = temp_str.replace("/", "\\")
                temp_linux = convert_to_linux_notation(temp_windows)
            else:
                # Currently in Linux notation
                temp_linux = temp_str.replace("\\", "/")
                temp_windows = convert_to_windows_notation(temp_linux)

            # Get project directory paths in both notations
            proj_str = str(self.PROJECT_ROOT)
            if proj_str.count("\\") > proj_str.count("/"):
                # Windows notation
                proj_windows = proj_str.replace("/", "\\")
                proj_linux = convert_to_linux_notation(proj_windows)
            else:
                # Linux notation
                proj_linux = proj_str.replace("\\", "/")
                proj_windows = convert_to_windows_notation(proj_linux)

            # Store all paths
            runtime["temp_root"] = str(temp_root)
            runtime["csc_agent_work"] = str(temp_root / "csc")
            runtime["project_tmp"] = str(temp_root)
            runtime["temp_dir_windows"] = temp_windows
            runtime["temp_dir_linux"] = temp_linux
            runtime["proj_dir_windows"] = proj_windows
            runtime["proj_dir_linux"] = proj_linux

        except Exception as e:
            self.log(f"[Platform] Failed to detect runtime directories: {e}")
            runtime["temp_root"] = None
            runtime["csc_agent_work"] = None
            runtime["temp_dir_windows"] = None
            runtime["temp_dir_linux"] = None
            runtime["proj_dir_windows"] = None
            runtime["proj_dir_linux"] = None

        return runtime

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def agent_temp_root(self):
        """Get system temp directory path."""
        runtime = self.platform_data.get("runtime", {})
        temp_root = runtime.get("temp_root")
        return Path(temp_root) if temp_root else None

    @property
    def agent_work_base(self):
        """Get CSC agent work base directory path."""
        runtime = self.platform_data.get("runtime", {})
        work_base = runtime.get("csc_agent_work")
        return Path(work_base) if work_base else None

    @property
    def run_dir(self):
        """Get the runtime state and log directory path."""
        runtime = self.platform_data.get("runtime", {})
        temp_root = runtime.get("temp_root")
        if not temp_root:
            temp_root = self.get_abs_tmp_path([])

        path = Path(temp_root) / "csc" / "run"
        import os
        os.makedirs(path, exist_ok=True)
        return path

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _get_platform_json_path(self):
        """Get the path for platform.json (in project root)."""
        return self.PROJECT_ROOT / self.PLATFORM_JSON_FILENAME

    def _persist_platform(self):
        """Write platform data to platform.json atomically."""
        filepath = self._get_platform_json_path()
        try:
            tmp = filepath.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.platform_data, f, indent=2, default=str)
                f.flush()
                os.fsync(f.fileno())
            tmp.replace(filepath)
            self.log(f"[Platform] Persisted inventory to {filepath}")
        except Exception as e:
            self.log(f"[Platform] Failed to persist platform.json: {e}")

    def _install_background_services(self):
        """Install background service scripts (queue-worker, test-runner) when install-at-startup flag is active."""
        try:
            bin_dir = self.PROJECT_ROOT / "bin"
            services_to_check = [
                "queue-worker",
                "cleanup-stuck-prompts",
            ]

            installed = []
            for service in services_to_check:
                script = bin_dir / service
                bat_wrapper = bin_dir / f"{service}.bat"
                if script.exists() or bat_wrapper.exists():
                    installed.append(service)

            if not installed:
                self.log("[Platform] No background service scripts found in bin/")
                return

            self.log(f"[Platform] Background services detected: {', '.join(installed)}")

            # Platform-specific setup
            if sys.platform == "win32":
                self._setup_windows_services()
            elif sys.platform == "linux" or sys.platform == "darwin":
                self._setup_unix_services()
            elif sys.platform == "linux" and os.path.exists("/data/data/com.termux"):
                # Android/Termux
                self._setup_android_services()

        except Exception as e:
            self.log(f"[Platform] Error installing background services: {e}")

    def _setup_windows_services(self):
        """Setup Windows Task Scheduler for background services."""
        try:
            # Check if setup script exists
            setup_script = self.PROJECT_ROOT / "bin" / "setup-tasks.bat"
            if not setup_script.exists():
                self.log("[Platform] bin/setup-tasks.bat not found")
                return

            self.log("[Platform] Windows detected - background services ready for Task Scheduler")
            self.log(f"[Platform] To activate: Run as Administrator: python {setup_script}")
            self.log("[Platform] Services will run: Queue Worker (every 2 min), Test Runner (every 5 min)")

        except Exception as e:
            self.log(f"[Platform] Windows setup error: {e}")

    def _setup_unix_services(self):
        """Setup Linux/macOS cron entries for background services."""
        try:
            queue_worker = self.PROJECT_ROOT / "bin" / "queue-worker"
            test_runner = self.PROJECT_ROOT / "tests" / "run_tests.sh"

            if not queue_worker.exists() or not test_runner.exists():
                self.log("[Platform] Background service scripts not found")
                return

            self.log("[Platform] Unix detected - background services ready for cron")
            self.log(f"[Platform] To activate: crontab -e and add:")
            self.log(f"[Platform]   */2 * * * * {queue_worker} >> {self.PROJECT_ROOT}/logs/queue-worker.log 2>&1")
            self.log(f"[Platform]   */5 * * * * bash {test_runner} >> {self.PROJECT_ROOT}/logs/test-runner.log 2>&1")

        except Exception as e:
            self.log(f"[Platform] Unix setup error: {e}")

    def _setup_android_services(self):
        """Setup Android/Termux services (requires manual cron or SystemD user service)."""
        try:
            self.log("[Platform] Android/Termux detected - background services available")
            self.log("[Platform] To activate: Set up cron (pkg install cronie) or write a wrapper script")

        except Exception as e:
            self.log(f"[Platform] Android setup error: {e}")

    @staticmethod
    def load_platform_json(path=None):
        """Load platform.json from disk. Static method for use by services."""
        path = Path(path) if path else (Platform.PROJECT_ROOT / Platform.PLATFORM_JSON_FILENAME)
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}

    # ------------------------------------------------------------------
    # Capability checking (used by prompt routing)
    # ------------------------------------------------------------------

    def has_tool(self, tool_name):
        """Check if a software tool is installed."""
        software = self.platform_data.get("software", {})
        tool_info = software.get(tool_name, {})
        if tool_info.get("installed"):
            return True

        # Also check AI agents
        agents = self.platform_data.get("ai_agents", {})
        agent_info = agents.get(tool_name, {})
        return agent_info.get("installed", False)

    def has_docker(self):
        """Check if Docker is usable."""
        return self.platform_data.get("docker", {}).get("usable", False)

    def matches_platform(self, required_platforms):
        """Check if this system matches one of the required platforms."""
        if not required_platforms:
            return True
        os_info = self.platform_data.get("os", {})
        system = os_info.get("system", "").lower()
        plat = os_info.get("platform", "").lower()
        dist = os_info.get("distribution", "").lower()

        for req in required_platforms:
            req = req.lower()
            if req in (system, plat):
                return True
            if req == "android" and os_info.get("is_android"):
                return True
            if req in dist:
                return True
        return False

    def has_min_ram(self, min_ram_str):
        """Check if system meets minimum RAM requirement."""
        if not min_ram_str:
            return True
        required_bytes = _parse_size(min_ram_str)
        hw = self.platform_data.get("hardware", {})
        available_mb = hw.get("ram_total_mb", 0)
        available_bytes = available_mb * 1024 * 1024
        return available_bytes >= required_bytes

    def check_requirements(self, requires=None, platform_list=None, min_ram=None):
        """Check if this system satisfies all requirements.

        Returns (satisfied: bool, reasons: list[str]) tuple.
        """
        reasons = []

        if requires:
            for tool in requires:
                tool_lower = tool.lower()
                if tool_lower == "docker":
                    if not self.has_docker():
                        reasons.append(f"Docker not available (installed={self.platform_data.get('docker', {}).get('installed', False)}, daemon={self.platform_data.get('docker', {}).get('daemon_running', False)})")
                elif not self.has_tool(tool_lower):
                    reasons.append(f"Tool '{tool}' not installed")

        if platform_list and not self.matches_platform(platform_list):
            os_info = self.platform_data.get("os", {})
            reasons.append(f"Platform mismatch: need {platform_list}, have {os_info.get('system', 'unknown')}")

        if min_ram and not self.has_min_ram(min_ram):
            hw = self.platform_data.get("hardware", {})
            reasons.append(f"Insufficient RAM: need {min_ram}, have {hw.get('ram_total_mb', 0)}MB")

        return (len(reasons) == 0, reasons)

    # ------------------------------------------------------------------
    # S2S Certificate Checking
    # ------------------------------------------------------------------

    @classmethod
    def check_s2s_cert(cls, config=None):
        """Check the S2S TLS certificate status.

        Reads ``s2s_cert`` path from csc-service.json (or the provided config
        dict) and validates the certificate.

        Returns:
            tuple: (ok: bool, reason: str)
                - ok=True, reason="valid" if cert is present and not expiring
                - ok=False, reason describing the issue otherwise
        """
        import subprocess as _sp

        # Load config if not provided
        if config is None:
            config_file = cls.PROJECT_ROOT / "csc-service.json"
            if config_file.exists():
                try:
                    config = json.loads(config_file.read_text(encoding="utf-8"))
                except Exception:
                    config = {}
            else:
                config = {}

        cert_path = config.get("s2s_cert", "")
        if not cert_path:
            return (False, "s2s_cert not configured in csc-service.json")

        cert_file = Path(cert_path)
        if not cert_file.exists():
            return (False, f"certificate file not found: {cert_path}")

        # Check if cert is valid (not expired)
        try:
            result = _sp.run(
                ["openssl", "x509", "-in", str(cert_file),
                 "-noout", "-checkend", "0"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                return (False, "certificate has expired")
        except FileNotFoundError:
            return (False, "openssl not found — cannot validate certificate")
        except Exception as e:
            return (False, f"error checking certificate: {e}")

        # Check if cert expires within 30 days (2592000 seconds)
        try:
            result = _sp.run(
                ["openssl", "x509", "-in", str(cert_file),
                 "-noout", "-checkend", "2592000"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                return (True, "certificate expiring within 30 days — renewal recommended")
        except Exception:
            pass

        # Check CRL revocation
        crl_path = config.get("s2s_crl", "")
        if crl_path and Path(crl_path).exists():
            try:
                serial_result = _sp.run(
                    ["openssl", "x509", "-in", str(cert_file),
                     "-noout", "-serial"],
                    capture_output=True, text=True, timeout=10,
                )
                if serial_result.returncode == 0:
                    serial = serial_result.stdout.strip().split("=")[-1]
                    crl_result = _sp.run(
                        ["openssl", "crl", "-in", crl_path,
                         "-noout", "-text"],
                        capture_output=True, text=True, timeout=10,
                    )
                    if crl_result.returncode == 0:
                        if serial.upper() in crl_result.stdout.upper():
                            return (False, f"certificate serial {serial} is revoked in CRL")
            except Exception:
                pass

        return (True, "valid")

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------

    def refresh_platform(self):
        """Re-run all detection and persist."""
        self._detect_all()
        self._persist_platform()
        return self.platform_data

    # ------------------------------------------------------------------
    # Path Management (get_abs_root_path, get_abs_tmp_path, store/load)
    # ------------------------------------------------------------------

    def get_abs_root_path(self, components):
        """Return absolute path from PROJECT_ROOT.

        Args:
            components: list of path components, e.g., ['irc', 'wo', 'ready']

        Returns:
            str: Absolute path under project root (platform-native separators)
        """
        root = Path(self.PROJECT_ROOT)
        for comp in components:
            root = root / comp
        return str(root)

    def get_abs_tmp_path(self, components):
        """Return absolute path from TMP directory (PROJECT_ROOT/tmp).

        Args:
            components: list of path components, e.g., ['agent-123', 'work']

        Returns:
            str: Absolute path to temp location
        """
        tmp_dir = Path(self.PROJECT_ROOT) / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        for comp in components:
            tmp_dir = tmp_dir / comp
        return str(tmp_dir)

    def store_path(self, name, path_type, components):
        """Store a path reference in platform.json for later retrieval.

        Args:
            name: Name identifier for this path (e.g., 'wo_ready', 'agent_work')
            path_type: Type of path - 'root', 'tmp', or 'abs'
            components: List of path components
        """
        if path_type == 'root':
            abs_path = self.get_abs_root_path(components)
        elif path_type == 'tmp':
            abs_path = self.get_abs_tmp_path(components)
        else:
            abs_path = str(Path(*components))

        # Store in platform_data under a 'paths' section
        if 'paths' not in self.platform_data:
            self.platform_data['paths'] = {}

        self.platform_data['paths'][name] = {
            'path': abs_path,
            'type': path_type,
            'components': components
        }
        self._persist_platform()

    def load_path(self, name):
        """Retrieve a stored path reference.

        Args:
            name: Name identifier previously stored with store_path()

        Returns:
            str: Absolute path, or None if not found
        """
        paths = self.platform_data.get('paths', {})
        if name in paths:
            return paths[name].get('path')
        return None

    def export_env_paths(self):
        """Export critical paths as environment variables.

        Sets environment variables that scripts (.bat, .sh) can use:
        - CSC_ROOT: Project root directory
        - CSC_TMP: Temporary directory
        - CSC_OPS_WO: Workorder pool directory
        - CSC_LOGS: Logs directory
        """
        os.environ['CSC_ROOT'] = str(self.PROJECT_ROOT)
        os.environ['CSC_TMP'] = self.get_abs_tmp_path([])
        os.environ['CSC_OPS_WO'] = self.get_abs_root_path(['ops', 'wo'])
        os.environ['CSC_OPS_AGENTS'] = self.get_abs_root_path(['ops', 'agents'])
        os.environ['CSC_DOCS'] = self.get_abs_root_path(['docs'])
        os.environ['CSC_DOCS_TOOLS'] = self.get_abs_root_path(['docs', 'tools'])
        os.environ['CSC_LOGS'] = self.get_abs_root_path(['logs'])
        os.environ['CSC_BIN'] = self.get_abs_root_path(['irc', 'bin'])


if __name__ == "__main__":
    p = Platform()
    print(json.dumps(p.platform_data, indent=2, default=str))
