#!/usr/bin/env python3
import os
import sys

STATE_FILE = "/opt/csc/tools/syslog_monitor.state"
LOG_FILE = "/var/log/syslog"

def get_last_pos():
    if not os.path.exists(STATE_FILE):
        return 0
    try:
        with open(STATE_FILE, "r") as f:
            return int(f.read().strip())
    except (ValueError, IOError):
        return 0

def set_last_pos(pos):
    try:
        with open(STATE_FILE, "w") as f:
            f.write(str(pos))
    except IOError:
        # Handle error, maybe log to stderr
        pass

def main():
    last_pos = get_last_pos()
    try:
        current_size = os.path.getsize(LOG_FILE)
        if current_size < last_pos:
            # Log file has been rotated or truncated
            last_pos = 0

        if current_size > last_pos:
            with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as f:
                f.seek(last_pos)
                new_lines = f.readlines()
                for line in new_lines:
                    print(line.strip())
            set_last_pos(current_size)

    except FileNotFoundError:
        # Silently exit if log file not found
        pass
    except Exception as e:
        # Log error to stderr for debugging
        print(f"Error reading log file: {e}", file=sys.stderr)

if __name__ == "__main__":
    main()
