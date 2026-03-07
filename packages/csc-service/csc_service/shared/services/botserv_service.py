"""
BotServ Service - Bot registration and management for channels.

Commands (via /msg BotServ):
  ADD <botnick> <#chan> <password> - Register a bot for a channel
  DEL <botnick> <#chan>            - Unregister a bot
  LIST [#chan]                     - List registered bots

Data storage: managed by PersistentStorageManager (botserv.json)
"""

import time
from pathlib import Path
from csc_service.server.service import Service
import subprocess
import re
import os
import sys

class Botserv(Service):
    """
    BotServ service for channel bot management.
    """

    def __init__(self, server_instance):
        """Initialize the BotServ service."""
        super().__init__(server_instance)
        self.name = "botserv"
        self.log("BotServ service initialized.")

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
        channel = args[0]
        pattern = args[1]
        
        try:
            re.compile(pattern) # Validate regex
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
        channel = args[0]
        pattern = args[1]
        
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
        channel = args[0]
        pattern = args[1]
        
        try:
            re.compile(pattern) # Validate regex
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
        channel = args[0]
        pattern = args[1]
        
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
            "  /msg BotServ ADDMATCH <botnick> <#chan> <pattern>    - Add a match filter pattern for a channel\n"
            "  /msg BotServ DELMATCH <botnick> <#chan> <pattern>    - Delete a match filter pattern for a channel\n"
            "  /msg BotServ ADDNOMATCH <botnick> <#chan> <pattern> - Add a nomatch filter pattern for a channel\n"
            "  /msg BotServ DELNOMATCH <botnick> <#chan> <pattern> - Delete a nomatch filter pattern for a channel\n"
            "  /msg BotServ LISTFILTERS <botnick> <#chan>           - List all match and nomatch filters for a channel\n"
            "  /msg BotServ LOGREAD <#chan> <logfile_path> [filter_pattern] - Read logfile to channel with optional filtering"
        )

    def logread(self, *args, filter_pattern: str = None) -> str:
        """LOGREAD <#chan> <logfile_path> [filter_pattern] - Read logfile to channel with optional filtering."""
        if len(args) < 2:
            return "Error: LOGREAD requires channel and logfile path. Usage: LOGREAD <#chan> <logfile_path> [filter_pattern]"

        channel = args[0]
        logfile_path = args[1]
        if len(args) > 2:
            filter_pattern = args[2]

        # Basic validation for channel format (starts with #)
        if not channel.startswith('#'):
            return "Error: Invalid channel format. Channel must start with #."

        # Use self.server.storage for persistent data
        storage_key = f"botserv_logread_offset_{channel}_{logfile_path}"
        last_read_offset = self.server.storage.get(storage_key, 0)
        
        script_path = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "server", "scripts", "read_privileged_log.py"))
        
        try:
            # Call the privileged script
            command = [sys.executable, script_path, logfile_path, str(last_read_offset)]
            process = subprocess.run(command, capture_output=True, text=True, check=True)

            new_content_raw = process.stdout
            
            # Extract total_bytes_read from stderr
            total_bytes_read_str = [line for line in process.stderr.splitlines() if line.startswith("TOTAL_BYTES_READ:")]
            if total_bytes_read_str:
                total_bytes_read = int(total_bytes_read_str[0].split(":")[1])
            else:
                self.log(f"Warning: Could not find TOTAL_BYTES_READ in script output for {logfile_path}. Assuming current offset is file size.")
                total_bytes_read = len(new_content_raw.encode('utf-8')) # Fallback: assume script returned entire new content

            self.server.storage.set(storage_key, total_bytes_read)
            
            new_lines = new_content_raw.splitlines()

            # Retrieve channel-specific match and nomatch filters
            channel_match_filters = [re.compile(p, re.IGNORECASE) for p in self.server.storage.get(f"botserv_match_filters_{channel}", [])]
            channel_nomatch_filters = [re.compile(p, re.IGNORECASE) for p in self.server.storage.get(f"botserv_nomatch_filters_{channel}", [])]

            compiled_arg_filter_pattern = None
            if filter_pattern:
                try:
                    compiled_arg_filter_pattern = re.compile(filter_pattern, re.IGNORECASE)
                    self.server.send_to_channel(channel, f"Applying argument filter: '{filter_pattern}'")
                except re.error as e:
                    return f"Error: Invalid argument filter pattern '{filter_pattern}': {e}"

            matched_lines_count = 0
            lines_sent = 0
            
            if not new_lines and last_read_offset > 0:
                self.server.send_to_channel(channel, f"No new lines in '{logfile_path}'.")
                return f"Successfully checked log '{logfile_path}'. No new lines."
            elif not new_lines and last_read_offset == 0:
                 self.server.send_to_channel(channel, f"Log '{logfile_path}' is empty or not yet processed.")
                 return f"Successfully checked log '{logfile_path}'. Empty or first read."

            self.server.send_to_channel(channel, f"Starting to read new lines from: {logfile_path}")
            for line in new_lines:
                # Apply nomatch filters first
                if any(nomatch_filter.search(line) for nomatch_filter in channel_nomatch_filters):
                    continue # Skip this line

                # Apply match filters (if any exist)
                if channel_match_filters and not any(match_filter.search(line) for match_filter in channel_match_filters):
                    continue # Skip this line if it doesn't match any required pattern

                # Apply argument filter if present
                if compiled_arg_filter_pattern is None or compiled_arg_filter_pattern.search(line):
                    self.server.send_to_channel(channel, line.strip())
                    matched_lines_count += 1
                lines_sent += 1
            
            filter_summary = []
            if compiled_arg_filter_pattern:
                filter_summary.append(f"argument filter '{filter_pattern}'")
            if channel_match_filters:
                filter_summary.append("channel match filters")
            if channel_nomatch_filters:
                filter_summary.append("channel nomatch filters")

            if filter_summary:
                self.server.send_to_channel(channel, f"Finished reading new lines with {', '.join(filter_summary)}. {matched_lines_count} matching lines out of {lines_sent} new lines found.")
            else:
                self.server.send_to_channel(channel, f"Finished reading new lines from: {logfile_path}. Total new lines: {lines_sent}")
            
            return f"Successfully processed new lines from '{logfile_path}' to '{channel}'. Matched lines: {matched_lines_count}"
        except FileNotFoundError:
            return f"Error: Log reading script not found or permissions issue: {script_path}"
        except subprocess.CalledProcessError as e:
            return f"Error executing log script for {logfile_path}: {e.stderr}"
        except Exception as e:
            self.server.send_to_channel(channel, f"Error processing logfile {logfile_path}: {e}")
            return f"Error processing logfile {logfile_path}: {e}"

    
