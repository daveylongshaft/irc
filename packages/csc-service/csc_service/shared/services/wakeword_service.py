"""
Wakeword Service - Manages global wakeword list for AI message filtering.

Wakewords are words or phrases that, when present in a channel message,
cause the message to be forwarded to AI clients that have wakeword
filtering enabled. This reduces API token waste by only sending relevant
messages to AI agents.

Storage: wakewords.json in the server's storage directory, using the
same atomic write pattern (temp + fsync + rename) as all other storage.

Commands:
    wakeword add <word_or_phrase>   - Add a wakeword (case-insensitive)
    wakeword del <word_or_phrase>   - Remove a wakeword
    wakeword list                   - Show all wakewords
"""

import json
import os

try:
    from csc_service.server.service import Service
except ImportError:
    try:
        from csc_service.server.service import Service
    except ImportError:
        from service import Service


# Default path for wakewords storage
WAKEWORDS_FILE = "wakewords.json"
WAKEWORDS_DEFAULT = {"version": 1, "words": []}


class wakeword(Service):
    """Wakeword management service for AI message filtering."""

    def __init__(self, server_instance):
        super().__init__(server_instance)
        self.name = "wakeword"

    def _get_storage_path(self):
        """Get the path to wakewords.json."""
        base = getattr(self.server, 'storage', None)
        if base and hasattr(base, 'base_path'):
            return os.path.join(base.base_path, WAKEWORDS_FILE)
        # Fallback: use the standard server storage location
        return os.path.join("/opt/csc/packages/csc_server", WAKEWORDS_FILE)

    def _load_wakewords(self):
        """Load wakewords from disk. Returns list of lowercase words."""
        path = self._get_storage_path()
        try:
            with open(path, "r") as f:
                data = json.load(f)
            return [w.lower() for w in data.get("words", [])]
        except (OSError, json.JSONDecodeError, KeyError):
            return []

    def _save_wakewords(self, words):
        """Save wakewords to disk atomically."""
        path = self._get_storage_path()
        data = {"version": 1, "words": sorted(set(words))}
        tmp_path = path + ".tmp"
        try:
            with open(tmp_path, "w") as f:
                json.dump(data, f, indent=2)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
            return True
        except Exception as e:
            self.log(f"[WAKEWORD] Error saving wakewords: {e}")
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            return False

    def add(self, *args) -> str:
        """Add a wakeword (case-insensitive).

        Usage: wakeword add <word_or_phrase>
        """
        if not args:
            return "Usage: wakeword add <word_or_phrase>"
        word = " ".join(args).lower().strip()
        if not word:
            return "Usage: wakeword add <word_or_phrase>"

        words = self._load_wakewords()
        if word in words:
            return f"Wakeword '{word}' already exists."

        words.append(word)
        if self._save_wakewords(words):
            return f"Wakeword '{word}' added. Total: {len(words)}"
        return "Error saving wakeword."

    def delete(self, *args) -> str:
        """Remove a wakeword.

        Usage: wakeword del <word_or_phrase>
        """
        if not args:
            return "Usage: wakeword del <word_or_phrase>"
        word = " ".join(args).lower().strip()
        if not word:
            return "Usage: wakeword del <word_or_phrase>"

        words = self._load_wakewords()
        if word not in words:
            return f"Wakeword '{word}' not found."

        words.remove(word)
        if self._save_wakewords(words):
            return f"Wakeword '{word}' removed. Total: {len(words)}"
        return "Error saving wakeword."

    # Alias: 'del' is a Python keyword so we use __getattr__ fallback
    def __getattr__(self, name):
        if name == 'del':
            return self.delete
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

    # Also support 'remove' as an alias
    def remove(self, *args) -> str:
        """Alias for delete."""
        return self.delete(*args)

    def list(self, *args) -> str:
        """Show all wakewords.

        Usage: wakeword list
        """
        words = self._load_wakewords()
        if not words:
            return "No wakewords configured."
        word_list = ", ".join(sorted(words))
        return f"Wakewords ({len(words)}): {word_list}"

    def default(self, *args) -> str:
        """Show available wakeword commands."""
        return (
            "Wakeword Service - AI Message Filtering:\n"
            "  add <word_or_phrase>   - Add a wakeword (case-insensitive)\n"
            "  del <word_or_phrase>   - Remove a wakeword\n"
            "  delete <word_or_phrase> - Remove a wakeword\n"
            "  list                   - Show all wakewords\n"
            "\n"
            "Wakewords trigger message forwarding to AI clients with filtering enabled."
        )
