"""Windows service detection and management using NSSM."""

import os
import sys
import subprocess
import re
import json
import zipfile
import tempfile
import urllib.request
import shutil
from pathlib import Path
from typing import List, Dict, Optional, Tuple


class WindowsServiceDetector:
    """Detect Windows services related to CSC."""

    SERVICE_PREFIX = "CSC-"

    @staticmethod
    def list_services() -> List[Dict]:
        """List all CSC-related Windows services."""
        try:
            # Use PowerShell to list services
            cmd = [
                "powershell", "-NoProfile", "-Command",
                f"Get-Service | Where-Object {{ $_.Name -like '{WindowsServiceDetector.SERVICE_PREFIX}*' }} | Select-Object Name, Status, StartType | ConvertTo-Json"
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode == 0 and result.stdout.strip():
                data = json.loads(result.stdout)
                if isinstance(data, dict):
                    return [data]
                return data
            return []
        except Exception:
            return []

    @staticmethod
    def get_service_status(service_name: str) -> Optional[Dict]:
        """Get status of a specific service."""
        try:
            cmd = [
                "powershell", "-NoProfile", "-Command",
                f"Get-Service -Name '{service_name}' | Select-Object Name, Status, StartType | ConvertTo-Json"
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode == 0 and result.stdout.strip():
                return json.loads(result.stdout)
            return None
        except Exception:
            return None

    @staticmethod
    def service_exists(service_name: str) -> bool:
        """Check if a service exists."""
        return WindowsServiceDetector.get_service_status(service_name) is not None


class WindowsServiceProvider:
    """Install/manage services on Windows using NSSM."""

    NSSM_URL = "https://nssm.cc/download/nssm-2.24-101-g897c7ad.zip"
    NSSM_VERSION = "2.24"

    def __init__(self, csc_root: Optional[str] = None):
        """Initialize Windows service provider."""
        self.csc_root = csc_root or os.environ.get("CSC_ROOT", "C:\\csc")
        self.nssm_path = self._find_or_install_nssm()

    def _find_or_install_nssm(self) -> Optional[str]:
        """Find NSSM executable, install if needed."""
        # Check if NSSM is on PATH
        nssm = shutil.which("nssm")
        if nssm:
            return nssm

        # Check CSC bin directory
        bin_nssm = Path(self.csc_root) / "bin" / "nssm.exe"
        if bin_nssm.exists():
            return str(bin_nssm)

        # Try to download and extract NSSM
        try:
            return self._download_nssm()
        except Exception as e:
            print(f"[WARN] Could not install NSSM: {e}")
            return None

    def _download_nssm(self) -> str:
        """Download and extract NSSM to csc/bin/."""
        print(f"[INFO] Downloading NSSM {self.NSSM_VERSION}...")

        with tempfile.TemporaryDirectory() as tmpdir:
            zip_path = Path(tmpdir) / "nssm.zip"
            urllib.request.urlretrieve(self.NSSM_URL, str(zip_path))

            with zipfile.ZipFile(zip_path, 'r') as z:
                z.extractall(tmpdir)

            nssm_exe = None
            for root, dirs, files in os.walk(tmpdir):
                if "nssm.exe" in files:
                    # Prefer 64-bit if available
                    if "win64" in root:
                        nssm_exe = Path(root) / "nssm.exe"
                        break
                    nssm_exe = Path(root) / "nssm.exe"

            if not nssm_exe:
                raise FileNotFoundError("nssm.exe not found in archive")

            bin_dir = Path(self.csc_root) / "bin"
            bin_dir.mkdir(parents=True, exist_ok=True)
            dest = bin_dir / "nssm.exe"
            shutil.copy(str(nssm_exe), str(dest))

            print(f"[OK] NSSM installed to {dest}")
            return str(dest)

    def install(self, service_name: str, module: str, args: str = "--daemon", auto_start: bool = True) -> Tuple[bool, str]:
        """Install a service using NSSM."""
        if not self.nssm_path:
            return (False, "NSSM not available")

        win_service_name = f"CSC-{service_name.upper()}" if not service_name.startswith("CSC-") else service_name

        if WindowsServiceDetector.service_exists(win_service_name):
            return (False, f"Service {win_service_name} already installed")

        try:
            python_exe = sys.executable
            log_dir = Path(self.csc_root) / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / f"{service_name.lower()}.log"

            # Install via NSSM
            # nssm install <name> <app> <args>
            install_cmd = [
                str(self.nssm_path), "install",
                win_service_name,
                python_exe,
                f"-m {module} {args}"
            ]
            result = subprocess.run(install_cmd, capture_output=True, text=True)
            if result.returncode != 0:
                return (False, f"NSSM install failed: {result.stderr}")

            # Set parameters
            subprocess.run([str(self.nssm_path), "set", win_service_name, "AppDirectory", str(self.csc_root)], capture_output=True)
            subprocess.run([str(self.nssm_path), "set", win_service_name, "AppStdout", str(log_file)], capture_output=True)
            subprocess.run([str(self.nssm_path), "set", win_service_name, "AppStderr", str(log_file)], capture_output=True)
            subprocess.run([str(self.nssm_path), "set", win_service_name, "AppRotateFiles", "1"], capture_output=True)
            
            if auto_start:
                subprocess.run([str(self.nssm_path), "set", win_service_name, "Start", "SERVICE_AUTO_START"], capture_output=True)

            return (True, f"Service {win_service_name} installed successfully")

        except Exception as e:
            return (False, f"Error installing service: {str(e)}")

    def uninstall(self, service_name: str) -> Tuple[bool, str]:
        """Uninstall a service."""
        if not self.nssm_path:
            return (False, "NSSM not available")

        win_service_name = f"CSC-{service_name.upper()}" if not service_name.startswith("CSC-") else service_name

        try:
            cmd = [str(self.nssm_path), "remove", win_service_name, "confirm"]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                return (False, f"NSSM remove failed: {result.stderr}")
            return (True, f"Service {win_service_name} uninstalled")
        except Exception as e:
            return (False, str(e))

    def start(self, service_name: str) -> Tuple[bool, str]:
        """Start a service."""
        if not self.nssm_path: return (False, "NSSM not available")
        win_service_name = f"CSC-{service_name.upper()}" if not service_name.startswith("CSC-") else service_name
        try:
            result = subprocess.run([str(self.nssm_path), "start", win_service_name], capture_output=True, text=True)
            if result.returncode != 0: return (False, result.stderr.strip())
            return (True, f"Service {win_service_name} started")
        except Exception as e: return (False, str(e))

    def stop(self, service_name: str) -> Tuple[bool, str]:
        """Stop a service."""
        if not self.nssm_path: return (False, "NSSM not available")
        win_service_name = f"CSC-{service_name.upper()}" if not service_name.startswith("CSC-") else service_name
        try:
            result = subprocess.run([str(self.nssm_path), "stop", win_service_name], capture_output=True, text=True)
            if result.returncode != 0: return (False, result.stderr.strip())
            return (True, f"Service {win_service_name} stopped")
        except Exception as e: return (False, str(e))
