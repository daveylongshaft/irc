```python
"""Tests for StatsService - SQLite event tracking system."""

import pytest
import sqlite3
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime

# Import the StatsService
from csc_service.shared.services.stats_service import StatsService


@pytest.fixture
def temp_db(tmp_path):
    """Create a temporary database for testing."""
    db_path = tmp_path / "test_stats.db"

    # Patch the STATS_DB_PATH before creating service
    with patch('csc_service.shared.services.stats_service.STATS_DB_PATH', db_path):
        service = StatsService()
        yield service
        service.close()


class TestStatsServiceInitialization:
    """Test database initialization and table creation."""

    def test_stats_service_creates_database(self, temp_db):
        """Verify StatsService creates database file."""
        service = temp_db
        assert service.conn is not None
        assert service.cursor is not None

    def test_all_tables_created(self, temp_db):
        """Verify all required tables are created."""
        service = temp_db

        # Query sqlite_master to check for tables
        service.cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = {row[0] for row in service.cursor.fetchall()}

        expected_tables = {
            'workorder_events',
            'system_events',
            'agent_events',
            'server_events'
        }

        assert expected_tables.issubset(tables), f"Missing tables: {expected_tables - tables}"

    def test_workorder_events_table_columns(self, temp_db):
        """Verify workorder_events table has correct columns."""
        service = temp_db
        service.cursor.execute("PRAGMA table_info(workorder_events)")
        columns = {row[1] for row in service.cursor.fetchall()}
        
        expected_columns = {
            'id', 'workorder_filename', 'event_type', 'timestamp',
            'duration', 'agent', 'result'
        }
        assert expected_columns.issubset(columns)

    def test_system_events_table_columns(self, temp_db):
        """Verify system_events table has correct columns."""
        service = temp_db
        service.cursor.execute("PRAGMA table_info(system_events)")
        columns = {row[1] for row in service.cursor.fetchall()}
        
        expected_columns = {
            'id', 'timestamp', 'event_type', 'source', 'severity', 'details'
        }
        assert expected_columns.issubset(columns)

    def test_agent_events_table_columns(self, temp_db):
        """Verify agent_events table has correct columns."""
        service = temp_db
        service.cursor.execute("PRAGMA table_info(agent_events)")
        columns = {row[1] for row in service.cursor.fetchall()}
        
        expected_columns = {
            'id', 'agent_name', 'timestamp', 'event_type',
            'status', 'workorder_id', 'details'
        }
        assert expected_columns.issubset(columns)

    def test_server_events_table_columns(self, temp_db):
        """Verify server_events table has correct columns."""
        service = temp_db
        service.cursor.execute("PRAGMA table_info(server_events)")
        columns = {row[1] for row in service.cursor.fetchall()}
        
        expected_columns = {
            'id', 'timestamp', 'event_type', 'client_addr', 'details'
        }
        assert expected_columns.issubset(columns)


class TestWorkorderEventLogging:
    """Test workorder event tracking."""

    def test_log_workorder_event(self, temp_db):
        """Test logging a workorder event."""
        service = temp_db

        service.log_event(
            workorder_filename="test_task.md",
            event_type="started",
            timestamp="2026-02-26T10:00:00",
            duration=0,
            agent="haiku",
            result="pending"
        )

        events = service.get_workorder_events("test_task.md")
        assert len(events) == 1
        assert events[0][1] == "test_task.md"  # workorder_filename
        assert events[0][2] == "started"  # event_type
        assert events[0][5] == "haiku"  # agent
        assert events[0][6] == "pending"  # result

    def test_log_workorder_event_with_defaults(self, temp_db):
        """Test logging a workorder event with default parameters."""
        service = temp_db

        service.log_event(
            workorder_filename="minimal_task.md",
            event_type="queued",
            timestamp="2026-02-26T10:00:00"
        )

        events = service.get_workorder_events("minimal_task.md")
        assert len(events) == 1
        assert events[0][4] == 0  # duration default
        assert events[0][5] is None  # agent default
        assert events[0][6] is None  # result default

    def test_get_all_workorder_events(self, temp_db):
        """Test retrieving all workorder events."""
        service = temp_db

        service.log_event("task1.md", "started", "2026-02-26T10:00:00", agent="haiku")
        service.log_event("task2.md", "completed", "2026-02-26T10:05:00", duration=5, agent="sonnet")

        all_events = service.get_all_events()
        assert len(all_events) == 2

    def test_get_workorder_events_by_filename(self, temp_db):
        """Test retrieving events for a specific workorder."""
        service = temp_db

        service.log_event("task1.md", "started", "2026-02-26T10:00:00", agent="haiku")
        service.log_event("task1.md", "completed", "2026-02-26T10:05:00", duration=5, agent="haiku")
        service.log_event("task2.md", "started", "2026-02-26T10:06:00", agent="sonnet")

        task1_events = service.get_workorder_events("task1.md")
        assert len(task1_events) == 2

        task2_events = service.get_workorder_events("task2.md")
        assert len(task2_events) == 1

    def test_get_workorder_events_nonexistent(self, temp_db):
        """Test retrieving events for a workorder that doesn't exist."""
        service = temp_db
        events = service.get_workorder_events("nonexistent.md")
        assert len(events) == 0

    def test_log_multiple_workorder_events(self, temp_db):
        """Test logging multiple events for the same workorder."""
        service = temp_db

        service.log_event("task.md", "started", "2026-02-26T10:00:00", agent="haiku", result="pending")
        service.log_event("task.md", "in_progress", "2026-02-26T10:01:00", agent="haiku", result="running")
        service.log_event("task.md", "completed", "2026-02-26T10:05:00", duration=5, agent="haiku", result="success")

        events = service.get_workorder_events("task.md")
        assert len(events) == 3
        assert events[0][2] == "started"
        assert events[1][2] == "in_progress"
        assert events[2][2] == "completed"


class TestSystemEventLogging:
    """Test generic system event tracking."""

    def test_log_system_event_with_string_details(self, temp_db):
        """Test logging a system event with string details."""
        service = temp_db

        service.log_system_event(
            event_type="startup",
            source="queue_worker",
            severity="INFO",
            details="Queue worker started successfully"
        )

        events = service.get_system_events(limit=1)
        assert len(events) == 1
        assert events[0][2] == "startup"  # event_type
        assert events[0][3] == "queue_worker"  # source
        assert events[0][4] == "INFO"  # severity
        assert events[0][5] == "Queue worker started successfully"  # details

    def test_log_system_event_with_dict_details(self, temp_db):
        """Test logging a system event with dict details (JSON serialization)."""
        service = temp_db

        details = {"worker_id": 123, "status": "active"}
        service.log_system_event(
            event_type="worker_status",
            source="queue_worker",
            severity="INFO",
            details=details
        )

        events = service.get_system_events(limit=1)
        assert len(events) == 1
        # Verify JSON was stored correctly
        stored_details = json.loads(events[0][5])
        assert stored_details["worker_id"] == 123
        assert stored_details["status"] == "active"

    def test_log_system_event_without_details(self, temp_db):
        """Test logging a system event without details."""
        service = temp_db

        service.log_system_event(
            event_type="test_event",
            source="test_source",
            severity="WARNING"
        )

        events = service.get_system_events(limit=1)
        assert len(events) == 1
        assert events[0][2] == "test_event"
        assert events[0][5] == ""  # empty details

    def test_log_system_event_with_default_severity(self, temp_db):
        """Test logging a system event with default severity."""
        service = temp_db

        service.log_system_event(
            event_type="default_severity_event",
            source="test_source"
        )

        events = service.get_system_events(limit=1)
        assert len(events) == 1
        assert events[0][4] == "INFO"  # default severity

    def test_get_system_events_limit(self, temp_db):
        """Test retrieving system events with limit."""
        service = temp_db

        for i in range(10):
            service.log_system_event(
                event_type=f"test_{i}",
                source="test_source",
                severity="INFO"
            )

        events = service.get_system_events(limit=5)
        assert len(events) == 5

    def test_system_events_ordered_by_timestamp(self, temp_db):
        """Test that system events are ordered by timestamp (newest first)."""
        service = temp_db

        service.log_system_event("event1", "source", severity="INFO")
        service.log_system_event("event2", "source", severity="INFO")
        service.log_system_event("event3", "source", severity="INFO")

        events = service.get_system_events(limit=10)
        # Most recent should be first (DESC order)
        assert len(events) == 3
        assert events[0][2] == "event3"
        assert events[1][2] == "event2"
        assert events[2][2] == "event1"

    def test_system_events_timestamp_format(self, temp_db):
        """Test that system events have ISO format timestamps."""
        service = temp_db

        service.log_system_event("test_event", "source", severity="INFO")

        events = service.get_system_events(limit=1)
        assert len(events) == 1
        timestamp = events[0][1]
        # Verify it's ISO format
        assert "T" in timestamp
        datetime.fromisoformat(timestamp)  # Will raise if not valid ISO


class TestAgentEventLogging:
    """Test agent execution event tracking."""

    def test_log_agent_event(self, temp_db):
        """Test logging an agent event."""
        service = temp_db

        service.log_agent_event(
            agent_name="haiku",
            event_type="execution_start",
            status="started",
            workorder_id="task_001",
            details=None
        )

        events = service.get_agent_events(agent_name="haiku", limit=1)
        assert len(events) == 1
        assert events[0][1] == "haiku"  # agent_name
        assert events[0][3] == "execution_start"  # event_type
        assert events[0][4] == "started"  # status
        assert events[0][5] == "task_001"  # workorder_id

    def test_log_agent_event_with_dict_details(self, temp_db):
        """Test logging an agent event with dict details."""
        service = temp_db

        details = {"tokens_used": 500, "model": "claude-3-haiku"}
        service.log_agent_event(
            agent_name="haiku",
            event_type="execution_complete",
            status="completed",
            workorder_id="task_001",
            details=details
        )

        events = service.get_agent_events(agent_name="haiku", limit=1)
        assert len(events) == 1
        stored_details = json.loads(events[0][6])
        assert stored_details["tokens_used"] == 500
        assert stored_details["model"] == "claude-3-haiku"

    def test_log_agent_event_with_string_details(self, temp_db):
        """Test logging an agent event with string details."""
        service = temp_db

        service.log_agent_event(
            agent_name="sonnet",
            event_type="error",
            status="failed",
            workorder_id="task_002",
            details="Agent encountered an error"
        )

        events = service.get_agent_events(agent_name="sonnet", limit=1)
        assert len(events) == 1
        assert events[0][6] == "Agent encountered an error"

    def test_get_agent_events_all(self, temp_db):
        """Test retrieving all agent events without filter."""
        service = temp_db

        service.log_agent_event("haiku", "start", "running", workorder_id="task_001")
        service.log_agent_event("sonnet", "start", "running", workorder_id="task_002")

        events = service.get_agent_events(limit=10)
        assert len(events) == 2

    def test_get_agent_events_filtered_by_name(self, temp_db):
        """Test retrieving agent events filtered by agent name."""
        service = temp_db

        service.log_agent_event("haiku", "start", "running", workorder_id="task_001")
        service.log_agent_event("haiku", "complete", "success", workorder_id="task_001")
        service.log_agent_event("sonnet", "start", "running", workorder_id="task_002")

        haiku_events = service.get_agent_events(agent_name="haiku", limit=10)
        assert len(haiku_events) == 2

        sonnet_events = service.get_agent_events(agent_name="sonnet", limit=10)
        assert len(sonnet_events) == 1

    def test_agent_events_ordered_by_timestamp(self, temp_db):
        """Test that agent events are ordered by timestamp (newest first)."""
        service = temp_db

        service.log_agent_event("haiku", "event1", "status1")
        service.log_agent_event("haiku", "event2", "status2")
        service.log_agent_event("haiku", "event3", "status3")

        events = service.get_agent_events(agent_name="haiku", limit=10)
        assert len(events) == 3
        assert events[0][3] == "event3"
        assert events