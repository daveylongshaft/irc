# StatsService - SQLite Event Tracking System

The `StatsService` module provides comprehensive event tracking and logging for the CSC (Client-Server-Commander) system. It uses SQLite to persistently store all system events, enabling analytics, debugging, and monitoring of the entire infrastructure.

## Overview

`StatsService` tracks four categories of events:
- **Workorder Events**: Lifecycle events of task processing (started, completed, failed)
- **System Events**: Generic system-level events with severity levels
- **Agent Events**: AI agent execution and status changes
- **Server Events**: IRC server operations and client interactions

## Installation

The StatsService is part of the `csc_service` package and can be imported directly:

```python
from csc_service.shared.services.stats_service import StatsService
```

## Usage

### Basic Initialization

```python
from csc_service.shared.services.stats_service import StatsService

# Create service instance - automatically creates database and tables
service = StatsService()

# Always close when done to properly flush and close the database connection
service.close()
```

### Database Location

The SQLite database is stored at:
```
packages/csc-service/csc_service/shared/services/stats_service/stats.db
```

The path is automatically determined using `pathlib.Path` for cross-platform compatibility.

## Logging Methods

### Workorder Event Logging

Track the lifecycle of workorder execution:

```python
service.log_event(
    workorder_filename="my_task.md",
    event_type="started",           # or "completed", "failed", etc.
    timestamp="2026-02-26T10:00:00",
    duration=0.0,                   # seconds
    agent="haiku",                  # which agent executed
    result="pending"                # or "success", "failure", etc.
)
```

### System Event Logging

Log generic system-level events with severity:

```python
service.log_system_event(
    event_type="startup",
    source="queue_worker",
    severity="INFO",                # INFO, WARNING, ERROR, DEBUG, CRITICAL
    details="Queue worker started"  # String or dict (auto JSON-serialized)
)

# With complex details (automatically JSON-serialized):
service.log_system_event(
    event_type="configuration_changed",
    source="csc-ctl",
    severity="INFO",
    details={"setting": "poll_interval", "value": 120, "previous": 60}
)
```

### Agent Event Logging

Track AI agent execution:

```python
service.log_agent_event(
    agent_name="haiku",
    event_type="execution_started",  # or "execution_completed", "execution_failed"
    status="running",                 # or "success", "failed", "timeout"
    workorder_id="task_001.md",
    details={"pid": 12345, "model": "claude-haiku-4-5"}
)
```

### Server Event Logging

Track IRC server operations:

```python
service.log_server_event(
    event_type="client_connected",   # or "client_disconnected", "channel_created"
    client_addr="127.0.0.1:54321",
    details={"nick": "test_user", "mode": "+i"}
)
```

## Query Methods

### Get Workorder Events

```python
# Get all events for a specific workorder
events = service.get_workorder_events("my_task.md")

# Get all workorder events
all_events = service.get_all_events()
```

### Get System Events

```python
# Get recent system events (default limit 100)
recent_events = service.get_system_events(limit=50)

# Returns list of tuples: (id, timestamp, event_type, source, severity, details)
for event in recent_events:
    event_id, timestamp, event_type, source, severity, details = event
    print(f"{timestamp} [{severity}] {event_type} from {source}: {details}")
```

### Get Agent Events

```python
# Get events for a specific agent
haiku_events = service.get_agent_events("haiku", limit=50)

# Get all agent events
all_agent_events = service.get_agent_events(limit=100)
```

### Get Server Events

```python
# Get server events
server_events = service.get_server_events(limit=50)
```

### Get Statistics

```python
# Get workorder event statistics by type
stats = service.get_event_stats()
# Returns: [(event_type, count, avg_duration), ...]

# Get summary of all tracked events
summary = service.get_event_summary()
# Returns dict:
# {
#     'total_workorder_events': 42,
#     'total_system_events': 156,
#     'total_agent_events': 89,
#     'total_server_events': 203
# }
```

## Database Schema

### workorder_events
Tracks workorder lifecycle:
- `id`: INTEGER PRIMARY KEY
- `workorder_filename`: TEXT
- `event_type`: TEXT (e.g., "started", "completed")
- `timestamp`: TEXT (ISO format)
- `duration`: FLOAT (seconds)
- `agent`: TEXT (agent name)
- `result`: TEXT (success/failure/pending)

### system_events
Tracks system-level events:
- `id`: INTEGER PRIMARY KEY
- `timestamp`: TEXT (ISO format, auto-generated)
- `event_type`: TEXT
- `source`: TEXT (component that generated event)
- `severity`: TEXT (INFO, WARNING, ERROR, DEBUG, CRITICAL)
- `details`: TEXT (JSON-serialized for complex data)

### agent_events
Tracks agent execution:
- `id`: INTEGER PRIMARY KEY
- `agent_name`: TEXT
- `timestamp`: TEXT (ISO format, auto-generated)
- `event_type`: TEXT
- `status`: TEXT (running, success, failed, timeout)
- `workorder_id`: TEXT
- `details`: TEXT (JSON-serialized)

### server_events
Tracks IRC server operations:
- `id`: INTEGER PRIMARY KEY
- `timestamp`: TEXT (ISO format, auto-generated)
- `event_type`: TEXT
- `client_addr`: TEXT (may be NULL)
- `details`: TEXT (JSON-serialized)

## Thread Safety

The StatsService is configured with `check_same_thread=False`, allowing it to be safely used across multiple threads. This is appropriate for a multi-threaded event logging system where different components may log events concurrently.

## JSON Serialization

When logging complex details (dictionaries), they are automatically JSON-serialized before storage. When retrieved, you can parse them back:

```python
import json

events = service.get_system_events(limit=1)
if events:
    event_id, timestamp, event_type, source, severity, details = events[0]
    details_dict = json.loads(details) if details else {}
    print(details_dict)
```

## Best Practices

1. **Always call `close()`**: Ensure the database connection is properly closed when done
   ```python
   try:
       # Use service
       service.log_system_event(...)
   finally:
       service.close()
   ```

2. **Use appropriate severity levels**: Choose severity based on event importance
   - `INFO`: Normal operation
   - `DEBUG`: Diagnostic information
   - `WARNING`: Something unexpected happened
   - `ERROR`: Something went wrong
   - `CRITICAL`: System-level failure

3. **Include contextual details**: Use the `details` parameter to store relevant context
   ```python
   service.log_agent_event(
       agent_name="sonnet",
       event_type="execution_failed",
       status="failed",
       workorder_id="task.md",
       details={
           "error": "API timeout",
           "retry_count": 3,
           "duration_ms": 45000
       }
   )
   ```

4. **Timestamps**: Timestamps are auto-generated in ISO format (UTC) for system, agent, and server events. For workorder events, you can provide a custom timestamp.

5. **Query limits**: Use the `limit` parameter to avoid loading excessive data
   ```python
   # Get last 10 events instead of all events
   recent = service.get_system_events(limit=10)
   ```

## Integration Examples

### Logging Agent Execution

```python
service = StatsService()

try:
    service.log_agent_event(
        agent_name="haiku",
        event_type="execution_started",
        status="running",
        workorder_id="build_task.md"
    )

    # ... execute task ...

    service.log_agent_event(
        agent_name="haiku",
        event_type="execution_completed",
        status="success",
        workorder_id="build_task.md",
        details={"duration_seconds": 45}
    )
finally:
    service.close()
```

### Monitoring System Health

```python
service = StatsService()

# Check for recent errors
errors = service.get_system_events(limit=100)
recent_errors = [e for e in errors if e[4] == "ERROR"]

if recent_errors:
    print(f"Found {len(recent_errors)} errors in the last 100 events")
    for error in recent_errors[:5]:
        print(f"  {error[1]}: {error[5]}")
```

### Analytics

```python
service = StatsService()

# Get workorder event statistics
stats = service.get_event_stats()
print("Event Statistics:")
for event_type, count, avg_duration in stats:
    print(f"  {event_type}: {count} events, avg duration {avg_duration:.2f}s")

# Get overall summary
summary = service.get_event_summary()
print(f"Total events tracked: {sum(summary.values())}")
```

## Performance Considerations

- **Database size**: The SQLite database will grow over time. Consider archiving old events periodically.
- **Query limits**: Always use reasonable `limit` values to avoid loading entire tables into memory.
- **Indexing**: For production use with large datasets, add indexes on frequently queried columns (e.g., `agent_name`, `timestamp`).
- **Archival**: Implement event archival to keep the active database performant.

## Error Handling

```python
import sqlite3

service = StatsService()

try:
    service.log_system_event("test", "source")
except sqlite3.Error as e:
    print(f"Database error: {e}")
finally:
    service.close()
```

## See Also

- `tests/test_stats_service.py` - Comprehensive test suite with usage examples
- `CLAUDE.md` - CSC project documentation
