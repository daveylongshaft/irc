#!/usr/bin/env python3
"""
API Key Manager: Automatic rotation between multiple API keys when credits exhausted.

Supports multiple Anthropic accounts - when one hits credit limit, automatically
switches to the next key and retries.

Usage:
    from csc_service.shared.api_key_manager import APIKeyManager

    key_mgr = APIKeyManager()
    api_key = key_mgr.get_current_key()

    # After API call fails with credit exhaustion:
    if "credit balance is too low" in error_message:
        new_key = key_mgr.rotate_key()
"""

import json
import os
from pathlib import Path
from datetime import datetime


class APIKeyManager:
    """Manages rotation of Anthropic API keys across multiple accounts."""

    def __init__(self, config_path=None):
        """Initialize key manager.

        Args:
            config_path: Path to api_keys.json (default: PROJECT_ROOT/api_keys.json)
        """
        if config_path is None:
            # Default to PROJECT_ROOT/api_keys.json
            self.config_path = Path(__file__).resolve().parent.parent.parent / "api_keys.json"
        else:
            self.config_path = Path(config_path)

        self.keys = []
        self.current_index = 0
        self.load_config()

    def load_config(self):
        """Load API keys from config file."""
        if not self.config_path.exists():
            # No config file - check environment variable fallback
            env_key = os.getenv("ANTHROPIC_API_KEY")
            if env_key:
                self.keys = [env_key]
                self.current_index = 0
            return

        try:
            with open(self.config_path, 'r') as f:
                config = json.load(f)

            self.keys = config.get("anthropic_keys", [])
            self.current_index = config.get("current_key_index", 0)

            # Validate index
            if self.current_index >= len(self.keys):
                self.current_index = 0

        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Failed to load API keys config: {e}")
            # Fallback to environment variable
            env_key = os.getenv("ANTHROPIC_API_KEY")
            if env_key:
                self.keys = [env_key]
                self.current_index = 0

    def save_config(self):
        """Save current key index to config file."""
        if not self.keys or not self.config_path.exists():
            return

        try:
            # Read existing config
            with open(self.config_path, 'r') as f:
                config = json.load(f)

            # Update index
            config["current_key_index"] = self.current_index

            # Write back
            with open(self.config_path, 'w') as f:
                json.dump(config, f, indent=2)

        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Failed to save API key index: {e}")

    def get_current_key(self):
        """Get the currently active API key.

        Returns:
            str: API key, or None if no keys available
        """
        if not self.keys:
            return None

        return self.keys[self.current_index]

    def rotate_key(self):
        """Rotate to the next API key.

        Returns:
            str: The new API key, or None if no keys available
        """
        if not self.keys:
            return None

        # Move to next key (circular)
        self.current_index = (self.current_index + 1) % len(self.keys)

        # Save new index
        self.save_config()

        # Log rotation
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] [api-key-manager] Rotated to key #{self.current_index + 1}/{len(self.keys)}")

        return self.get_current_key()

    def get_key_count(self):
        """Get total number of API keys available.

        Returns:
            int: Number of keys
        """
        return len(self.keys)

    def is_credit_exhaustion_error(self, error_text):
        """Check if an error message indicates API credit exhaustion.

        Args:
            error_text: Error message text

        Returns:
            bool: True if this is a credit exhaustion error
        """
        credit_indicators = [
            "credit balance is too low",
            "insufficient credits",
            "quota exceeded",
            "rate limit exceeded"
        ]

        error_lower = str(error_text).lower()
        return any(indicator in error_lower for indicator in credit_indicators)
