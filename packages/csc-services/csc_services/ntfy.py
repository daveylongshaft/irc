import os
import subprocess
from datetime import datetime, timezone

from csc_services import Service


class ntfy(Service):
    """
    A dedicated service to send notifications via ntfy.sh.
    This service uses the 'curl' service as a reliable backend and logs all
    notifications to /var/log/ntfy.log (or ~/ntfy.log as fallback).
    """

    # --- All methods and variables must be indented inside the class ---
    TOPIC = "gemini_commander"
    NTFY_URL = f"https://ntfy.sh/{TOPIC}"

    def __init__(self, server_instance):
        """
        Initializes the instance.
        """
        super().__init__(server_instance)
        self.log(f"Ntfy service initialized for topic: {self.TOPIC}")

    def _write_log(self, log_line):
        """
        Write a log line to /var/log/ntfy.log (or ~/ntfy.log if not writable).
        """
        log_file = "/var/log/ntfy.log"
        try:
            with open(log_file, 'a') as f:
                f.write(log_line + '\n')
        except (IOError, OSError):
            # Fallback to home directory
            log_file = os.path.expanduser("~/ntfy.log")
            try:
                with open(log_file, 'a') as f:
                    f.write(log_line + '\n')
                self.log(f"WARNING: Could not write to /var/log/ntfy.log, using {log_file}")
            except (IOError, OSError) as e:
                self.log(f"ERROR: Could not write to ntfy log: {e}")

    def send(self, *args):
        """
        Sends a notification to the ntfy.sh topic.
        Usage: send <subject> <body>
        """
        if len(args) < 2:
            return "Error: Usage: ntfy send <subject> \"<body>\""

        subject, body = args[0], " ".join(args[1:])

        # It now correctly looks for loaded_modules on self.server
        curl_instance = self.server.loaded_modules.get("Curl")

        if not curl_instance:
            return "FATAL ERROR: The 'Curl' service is a required dependency but is not loaded."

        self.log(f"Sending notification to ntfy.sh topic '{self.TOPIC}' via curl.")

        # Get hostname and timestamp
        hostname = subprocess.run(
            ["hostname", "-s"],
            capture_output=True,
            text=True,
            timeout=5
        ).stdout.strip() or "unknown"

        iso8601 = datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
        caller = "ntfy_service"

        # Write log line BEFORE attempting curl
        log_line = f"{iso8601} | host={hostname} | caller={caller} | topic={self.TOPIC} | title={subject} | body={body}"
        self._write_log(log_line)

        # Construct the arguments for the curl service
        curl_args = [
            '-H', f"Title: {subject}",
            '-d', body,
            self.NTFY_URL
        ]

        result = curl_instance.run(*curl_args)

        # Log if curl failed (check if result indicates failure)
        if "Error" in result or "Failed" in result:
            fail_line = f"{iso8601} | host={hostname} | caller={caller} | SEND_FAILED"
            self._write_log(fail_line)

        return f"Notification sent. Curl service response: {result}"

    def default(self, *args):
        """
        Checks service status and shows the configured topic.
        Usage: ntfy
        """
        return f"Ntfy service is ready. Messages will be sent to topic '{self.TOPIC}'."