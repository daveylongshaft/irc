"""
Chat buffer logging and replay for csc-server.

Logs PRIVMSG/NOTICE messages to per-channel and per-PM log files in a
buffers/ directory.  Each file is trimmed to ~100KB (keeping newest ~75KB)
to bound disk usage.
"""

import os
import threading
import time
from datetime import datetime


class ChatBuffer:
    """
    Server-side message buffer that persists chat history to disk.

    One .log file per channel or PM pair, stored under a buffers/ directory
    relative to the project root.  Thread-safe via per-file locks.
    """

    MAX_SIZE = 100 * 1024      # 100 KB trigger
    TRIM_TARGET = 75 * 1024    # keep newest ~75 KB after trim

    def __init__(self, buffers_dir=None):
        """
        Initializes the instance.
        """
        if buffers_dir is None:
            # Default: buffers/ next to this file's grandparent (project root)
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            buffers_dir = os.path.join(project_root, "buffers")
        self.buffers_dir = buffers_dir
        os.makedirs(self.buffers_dir, exist_ok=True)

        # Per-file locks keyed by normalised target key
        self._locks = {}
        self._locks_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def append(self, target, sender_nick, command, text):
        """
        Append a timestamped log line for *target* (channel or PM nick).

        Args:
            target: Channel name (e.g. '#general') or recipient nick for PMs.
            sender_nick: The nick of the message author.
            command: 'PRIVMSG' or 'NOTICE'.
            text: The message body.
        """
        filepath = self._filepath_for(target, sender_nick)
        lock = self._get_lock(filepath)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] :{sender_nick} {command} {target} :{text}\n"

        with lock:
            with open(filepath, "a", encoding="utf-8") as f:
                f.write(line)
            self._trim_if_needed(filepath)

    def read(self, target, sender_nick=None, limit_bytes=None):
        """
        Return all buffered lines for *target* as a list of strings.

        For PM targets, *sender_nick* is needed to derive the canonical
        filename (nicks sorted alphabetically).
        
        Args:
            limit_bytes: If set, return roughly this many bytes from the end 
                         of the file (ensuring line integrity).
        """
        filepath = self._filepath_for(target, sender_nick)
        lock = self._get_lock(filepath)

        with lock:
            if not os.path.exists(filepath):
                return []
            
            with open(filepath, "r", encoding="utf-8") as f:
                if limit_bytes:
                    f.seek(0, 2) # Seek to end
                    size = f.tell()
                    if size > limit_bytes:
                        f.seek(max(0, size - limit_bytes))
                        # Read forward and discard partial line
                        f.readline()
                else:
                    f.seek(0)
                    
                return f.readlines()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _filepath_for(self, target, sender_nick=None):
        """
        Derive the log file path for a target.

        Channels: chan_general.log  (strip leading '#')
        PMs:      alice_bob.log    (nicks sorted alphabetically)
        """
        if target.startswith("#"):
            safe = target.lstrip("#").replace("/", "_").replace("\\", "_")
            filename = f"chan_{safe}.log"
        else:
            # PM — canonical key from sorted pair of nicks
            nicks = sorted([n.lower() for n in (sender_nick or "unknown", target)])
            filename = f"{'_'.join(nicks)}.log"
        return os.path.join(self.buffers_dir, filename)

    def _get_lock(self, filepath):
        """Return (or create) a per-file threading.Lock."""
        with self._locks_lock:
            if filepath not in self._locks:
                self._locks[filepath] = threading.Lock()
            return self._locks[filepath]

    def _trim_if_needed(self, filepath):
        """
        If *filepath* exceeds MAX_SIZE, truncate from the front keeping
        the newest ~TRIM_TARGET bytes, cutting at a newline boundary.

        Caller must already hold the per-file lock.
        """
        try:
            size = os.path.getsize(filepath)
        except OSError:
            return

        if size <= self.MAX_SIZE:
            return

        with open(filepath, "r", encoding="utf-8") as f:
            data = f.read()

        # Keep the tail of the file
        cut = len(data) - self.TRIM_TARGET
        if cut <= 0:
            return

        # Find first newline after the cut point so we don't split a line
        newline_pos = data.find("\n", cut)
        if newline_pos == -1:
            return  # entire file is one line — leave it
        trimmed = data[newline_pos + 1:]

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(trimmed)
