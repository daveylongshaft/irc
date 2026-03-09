import sqlite3
from pathlib import Path
from datetime import datetime
import json

STATS_DB_PATH = Path(__file__).parent / "stats.db"

class StatsService:
    """
    Tracks all system events in SQLite database.
    Supports workorder events, agent events, server events, and generic system events.
    """

    def __init__(self):
        self.conn = sqlite3.connect(str(STATS_DB_PATH), check_same_thread=False)
        self.cursor = self.conn.cursor()
        self._create_tables()

    def _create_tables(self):
        """Create all tables for event tracking if they don't exist."""
        # Workorder events table
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS workorder_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workorder_filename TEXT,
                event_type TEXT,
                timestamp TEXT,
                duration FLOAT,
                agent TEXT,
                result TEXT
            )
        """)

        # System events table (generic events tracking)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS system_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                event_type TEXT,
                source TEXT,
                severity TEXT,
                details TEXT
            )
        """)

        # Agent execution events
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS agent_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_name TEXT,
                timestamp TEXT,
                event_type TEXT,
                status TEXT,
                workorder_id TEXT,
                details TEXT
            )
        """)

        # Server events
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS server_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                event_type TEXT,
                client_addr TEXT,
                details TEXT
            )
        """)

        self.conn.commit()

    def log_event(self, workorder_filename, event_type, timestamp, duration=0, agent=None, result=None):
        """Log a workorder event."""
        self.cursor.execute(
            "INSERT INTO workorder_events (workorder_filename, event_type, timestamp, duration, agent, result) VALUES (?, ?, ?, ?, ?, ?)",
            (workorder_filename, event_type, timestamp, duration, agent, result)
        )
        self.conn.commit()

    def log_system_event(self, event_type, source, severity="INFO", details=None):
        """Log a generic system event."""
        timestamp = datetime.utcnow().isoformat()
        details_str = json.dumps(details) if details and not isinstance(details, str) else (details or "")
        self.cursor.execute(
            "INSERT INTO system_events (timestamp, event_type, source, severity, details) VALUES (?, ?, ?, ?, ?)",
            (timestamp, event_type, source, severity, details_str)
        )
        self.conn.commit()

    def log_agent_event(self, agent_name, event_type, status, workorder_id=None, details=None):
        """Log an agent execution event."""
        timestamp = datetime.utcnow().isoformat()
        details_str = json.dumps(details) if details and not isinstance(details, str) else (details or "")
        self.cursor.execute(
            "INSERT INTO agent_events (agent_name, timestamp, event_type, status, workorder_id, details) VALUES (?, ?, ?, ?, ?, ?)",
            (agent_name, timestamp, event_type, status, workorder_id, details_str)
        )
        self.conn.commit()

    def log_server_event(self, event_type, client_addr=None, details=None):
        """Log a server event."""
        timestamp = datetime.utcnow().isoformat()
        details_str = json.dumps(details) if details and not isinstance(details, str) else (details or "")
        self.cursor.execute(
            "INSERT INTO server_events (timestamp, event_type, client_addr, details) VALUES (?, ?, ?, ?)",
            (timestamp, event_type, client_addr, details_str)
        )
        self.conn.commit()

    def get_workorder_events(self, workorder_filename):
        """Get all events for a specific workorder."""
        self.cursor.execute("SELECT * FROM workorder_events WHERE workorder_filename = ?", (workorder_filename,))
        return self.cursor.fetchall()

    def get_all_events(self):
        """Get all workorder events."""
        self.cursor.execute("SELECT * FROM workorder_events")
        return self.cursor.fetchall()

    def get_system_events(self, limit=100):
        """Get recent system events."""
        self.cursor.execute("SELECT * FROM system_events ORDER BY timestamp DESC LIMIT ?", (limit,))
        return self.cursor.fetchall()

    def get_agent_events(self, agent_name=None, limit=100):
        """Get agent events, optionally filtered by agent name."""
        if agent_name:
            self.cursor.execute("SELECT * FROM agent_events WHERE agent_name = ? ORDER BY timestamp DESC LIMIT ?", (agent_name, limit))
        else:
            self.cursor.execute("SELECT * FROM agent_events ORDER BY timestamp DESC LIMIT ?", (limit,))
        return self.cursor.fetchall()

    def get_server_events(self, limit=100):
        """Get server events."""
        self.cursor.execute("SELECT * FROM server_events ORDER BY timestamp DESC LIMIT ?", (limit,))
        return self.cursor.fetchall()

    def get_event_stats(self):
        """Get statistics about workorder events by type."""
        self.cursor.execute("SELECT event_type, COUNT(*) as count, AVG(duration) as avg_duration FROM workorder_events GROUP BY event_type")
        return self.cursor.fetchall()

    def get_event_summary(self):
        """Get a summary of all tracked events."""
        summary = {}

        # Count events by type in workorder_events
        self.cursor.execute("SELECT COUNT(*) FROM workorder_events")
        summary['total_workorder_events'] = self.cursor.fetchone()[0]

        # Count events in system_events
        self.cursor.execute("SELECT COUNT(*) FROM system_events")
        summary['total_system_events'] = self.cursor.fetchone()[0]

        # Count events in agent_events
        self.cursor.execute("SELECT COUNT(*) FROM agent_events")
        summary['total_agent_events'] = self.cursor.fetchone()[0]

        # Count events in server_events
        self.cursor.execute("SELECT COUNT(*) FROM server_events")
        summary['total_server_events'] = self.cursor.fetchone()[0]

        return summary

    def close(self):
        """Close the database connection."""
        self.conn.close()