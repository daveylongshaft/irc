import json
import os
import shutil
import time
from pathlib import Path

class ConfigManager:
    def __init__(self, config_file=None):
        self.config_file = self._resolve_config_path(config_file)
        self.config = self.load_config()

    def _resolve_config_path(self, config_file):
        if config_file:
            return Path(config_file)

        # Explicit env var override
        if "CSC_CONFIG_FILE" in os.environ:
            return Path(os.environ["CSC_CONFIG_FILE"])

        # CSC_ETC env var (set by Platform.export_paths)
        csc_etc = os.environ.get("CSC_ETC", "")
        if csc_etc:
            return Path(csc_etc) / "csc-service.json"

        # Use Platform to resolve canonical etc dir
        try:
            from csc_platform.platform import Platform
            return Platform.get_etc_dir() / "csc-service.json"
        except (ImportError, AttributeError):
            pass

        # Last resort: CSC_ROOT env var
        csc_root = os.environ.get("CSC_ROOT", "")
        if csc_root:
            return Path(csc_root) / "etc" / "csc-service.json"

        raise RuntimeError(
            "Cannot resolve csc-service.json: csc-platform not available and "
            "CSC_ETC/CSC_ROOT env vars are not set"
        )

    def load_config(self):
        if self.config_file.exists():
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except json.JSONDecodeError:
                # Handle corrupted JSON file
                return {}
        return {"services": {}}

    def save_config(self):
        # Create backup
        backup_dir = self.config_file.parent / "backup"
        backup_dir.mkdir(exist_ok=True)
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        backup_path = backup_dir / f"{self.config_file.name}.backup.{timestamp}"
        if self.config_file.exists():
            shutil.copy2(self.config_file, backup_path)

        # Atomic write
        temp_path = self.config_file.with_suffix(".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(self.config, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        
        os.replace(temp_path, self.config_file)

    def get_value(self, key):
        keys = key.split('.')
        value = self.config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return None
        return value

    def set_value(self, key, value):
        keys = key.split('.')
        d = self.config
        for k in keys[:-1]:
            d = d.setdefault(k, {})
        d[keys[-1]] = value
        self.save_config()

    def get_service_config(self, service_name):
        return self.config.get("services", {}).get(service_name)

    def get_all_services_config(self):
        return self.config.get("services", {})
