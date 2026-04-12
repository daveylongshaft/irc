"""
BotServ Service - Bot registration and management for channels.

Commands (via /msg BotServ):
  ADD <botnick> <#chan> <password> - Register a bot for a channel
  DEL <botnick> <#chan>            - Unregister a bot
  LIST [#chan]                     - List registered bots

Data storage: managed by PersistentStorageManager (botserv.json)
"""

import re
from pathlib import Path
from csc_services import Service


# Paths that require privileged (sudo) access
PRIVILEGED_PREFIXES = ["/var/log/"]


class Botserv(Service):
    """
    BotServ service for channel bot management.
    """

    def __init__(self, server_instance):
        """Initialize the BotServ service."""
        super().__init__(server_instance)
        self.name = "botserv"
        self.log("BotServ service initialized.")

    def _is_privileged_path(self, path):
        """Check if a log path requires privileged access."""
        return any(str(path).startswith(p) for p in PRIVILEGED_PREFIXES)

    def _get_offset_key(self, channel, logfile_path):
        """Storage key for tracking read offset."""
        return f"botserv_logread_offset_{channel}_{logfile_path}"

    def _get_channel_filters(self, channel):
        """Load compiled match/nomatch filter patterns for a channel."""
        match_raw = self.server.storage.get(f"botserv_match_filters_{channel}", [])
        nomatch_raw = self.server.storage.get(f"botserv_nomatch_filters_{channel}", [])
        match = [re.compile(p, re.IGNORECASE) for p in match_raw]
        nomatch = [re.compile(p, re.IGNORECASE) for p in nomatch_raw]
        return match, nomatch

    def add(self, *args) -> str:
        """ADD <botnick> <#chan> <password>"""
        if len(args) < 3:
            return "Error: ADD requires botnick, channel and password. Usage: ADD <botnick> <#chan> <password>"
        return "Error: BotServ ADD must be called via PRIVMSG from the IRC server integration."

    def delete(self, *args) -> str:
        """DEL <botnick> <#chan>"""
        if len(args) < 2:
            return "Error: DEL requires botnick and channel. Usage: DEL <botnick> <#chan>"
        return "Error: BotServ DEL must be called via PRIVMSG from the IRC server integration."

    def list(self, *args) -> str:
        """LIST [#chan]"""
        return "Error: BotServ LIST must be called via PRIVMSG from the IRC server integration."

    def addmatch(self, *args) -> str:
        """ADDMATCH <#chan> <pattern> - Add a match filter pattern for a channel."""
        if len(args) < 2:
            return "Error: ADDMATCH requires channel and pattern. Usage: ADDMATCH <#chan> <pattern>"
        channel, pattern = args[0], args[1]

        try:
            re.compile(pattern)
        except re.error as e:
            return f"Error: Invalid regex pattern '{pattern}': {e}"

        filters = self.server.storage.get(f"botserv_match_filters_{channel}", [])
        if pattern not in filters:
            filters.append(pattern)
            self.server.storage.set(f"botserv_match_filters_{channel}", filters)
            return f"Match filter '{pattern}' added to {channel}."
        return f"Match filter '{pattern}' already exists for {channel}."

    def delmatch(self, *args) -> str:
        """DELMATCH <#chan> <pattern> - Delete a match filter pattern for a channel."""
        if len(args) < 2:
            return "Error: DELMATCH requires channel and pattern. Usage: DELMATCH <#chan> <pattern>"
        channel, pattern = args[0], args[1]

        filters = self.server.storage.get(f"botserv_match_filters_{channel}", [])
        if pattern in filters:
            filters.remove(pattern)
            self.server.storage.set(f"botserv_match_filters_{channel}", filters)
            return f"Match filter '{pattern}' removed from {channel}."
        return f"Match filter '{pattern}' not found for {channel}."

    def addnomatch(self, *args) -> str:
        """ADDNOMATCH <#chan> <pattern> - Add a nomatch filter pattern for a channel."""
        if len(args) < 2:
            return "Error: ADDNOMATCH requires channel and pattern. Usage: ADDNOMATCH <#chan> <pattern>"
        channel, pattern = args[0], args[1]

        try:
            re.compile(pattern)
        except re.error as e:
            return f"Error: Invalid regex pattern '{pattern}': {e}"

        filters = self.server.storage.get(f"botserv_nomatch_filters_{channel}", [])
        if pattern not in filters:
            filters.append(pattern)
            self.server.storage.set(f"botserv_nomatch_filters_{channel}", filters)
            return f"Nomatch filter '{pattern}' added to {channel}."
        return f"Nomatch filter '{pattern}' already exists for {channel}."

    def delnomatch(self, *args) -> str:
        """DELNOMATCH <#chan> <pattern> - Delete a nomatch filter pattern for a channel."""
        if len(args) < 2:
            return "Error: DELNOMATCH requires channel and pattern. Usage: DELNOMATCH <#chan> <pattern>"
        channel, pattern = args[0], args[1]

        filters = self.server.storage.get(f"botserv_nomatch_filters_{channel}", [])
        if pattern in filters:
            filters.remove(pattern)
            self.server.storage.set(f"botserv_nomatch_filters_{channel}", filters)
            return f"Nomatch filter '{pattern}' removed from {channel}."
        return f"Nomatch filter '{pattern}' not found for {channel}."

    def listfilters(self, *args) -> str:
        """LISTFILTERS <#chan> - List all match and nomatch filters for a channel."""
        if len(args) < 1:
            return "Error: LISTFILTERS requires a channel. Usage: LISTFILTERS <#chan>"
        channel = args[0]

        match_filters = self.server.storage.get(f"botserv_match_filters_{channel}", [])
        nomatch_filters = self.server.storage.get(f"botserv_nomatch_filters_{channel}", [])

        response = [f"Filters for {channel}:"]
        if match_filters:
            response.append("  Match Filters:")
            for f in match_filters:
                response.append(f"    - {f}")
        else:
            response.append("  No match filters set.")

        if nomatch_filters:
            response.append("  Nomatch Filters:")
            for f in nomatch_filters:
                response.append(f"    - {f}")
        else:
            response.append("  No nomatch filters set.")

        return "\n".join(response)

    def default(self, *args) -> str:
        """Show available BotServ commands."""
        return (
            "BotServ - Bot Registration Service\n"
            "Available commands:\n"
            "  /msg BotServ ADD <botnick> <#chan> <password>  - Register a bot\n"
            "  /msg BotServ DEL <botnick> <#chan>             - Unregister a bot\n"
            "  /msg BotServ LIST [#chan]                      - List registered bots\n"
            "  /msg BotServ ADDMATCH <#chan> <pattern>        - Add a match filter\n"
            "  /msg BotServ DELMATCH <#chan> <pattern>        - Delete a match filter\n"
            "  /msg BotServ ADDNOMATCH <#chan> <pattern>      - Add a nomatch filter\n"
            "  /msg BotServ DELNOMATCH <#chan> <pattern>      - Delete a nomatch filter\n"
            "  /msg BotServ LISTFILTERS <#chan>               - List all filters\n"
            "  /msg BotServ LOGREAD <#chan> <logfile_path> [filter] - Read log to channel"
        )

    def logread(self, *args, filter_pattern: str = None) -> str:
        """LOGREAD <#chan> <logfile_path> [filter_pattern] - Read logfile to channel with optional filtering."""
        if len(args) < 2:
            return "Error: LOGREAD requires channel and logfile path. Usage: LOGREAD <#chan> <logfile_path> [filter_pattern]"

        channel = args[0]
        logfile_path = args[1]
        if len(args) > 2:
            filter_pattern = args[2]

        if not channel.startswith('#'):
            return "Error: Invalid channel format. Channel must start with #."

        # Get stored offset via Data layer
        offset_key = self._get_offset_key(channel, logfile_path)
        last_offset = self.server.storage.get(offset_key, 0)

        # Read new lines -- privileged paths use Data._tail_privileged_log_file,
        # normal paths use Log._tail_log_file
        path = Path(logfile_path)
        try:
            if self._is_privileged_path(logfile_path):
                new_lines, new_offset = self._tail_privileged_log_file(path, last_offset)
            else:
                new_lines, new_offset = self._tail_log_file(path, last_offset)
        except Exception as e:
            self.server.send_to_channel(channel, f"Error reading {logfile_path}: {e}")
            return f"Error reading {logfile_path}: {e}"

        # Persist new offset
        self.server.storage.set(offset_key, new_offset)

        if not new_lines:
            if last_offset > 0:
                self.server.send_to_channel(channel, f"No new lines in '{logfile_path}'.")
            else:
                self.server.send_to_channel(channel, f"Log '{logfile_path}' is empty or not yet processed.")
            return f"Successfully checked log '{logfile_path}'. No new lines."

        # Load channel filters
        match_filters, nomatch_filters = self._get_channel_filters(channel)

        # Compile argument filter if provided
        compiled_arg_filter = None
        if filter_pattern:
            try:
                compiled_arg_filter = re.compile(filter_pattern, re.IGNORECASE)
                self.server.send_to_channel(channel, f"Applying filter: '{filter_pattern}'")
            except re.error as e:
                return f"Error: Invalid filter pattern '{filter_pattern}': {e}"

        # Apply filters and send to channel
        self.server.send_to_channel(channel, f"Reading new lines from: {logfile_path}")
        matched = 0
        total = len(new_lines)

        for line in new_lines:
            text = line.strip()
            if not text:
                continue

            # Nomatch filters (exclusion)
            if any(f.search(text) for f in nomatch_filters):
                continue

            # Match filters (inclusion -- all lines must match at least one)
            if match_filters and not any(f.search(text) for f in match_filters):
                continue

            # Argument filter
            if compiled_arg_filter and not compiled_arg_filter.search(text):
                continue

            self.server.send_to_channel(channel, text)
            matched += 1

        # Summary
        filter_parts = []
        if compiled_arg_filter:
            filter_parts.append(f"argument filter '{filter_pattern}'")
        if match_filters:
            filter_parts.append("channel match filters")
        if nomatch_filters:
            filter_parts.append("channel nomatch filters")

        if filter_parts:
            self.server.send_to_channel(channel, f"Done. {matched} matching lines out of {total} new lines ({', '.join(filter_parts)}).")
        else:
            self.server.send_to_channel(channel, f"Done. {total} new lines from: {logfile_path}")

        return f"Processed '{logfile_path}' to '{channel}'. {matched} lines delivered."
