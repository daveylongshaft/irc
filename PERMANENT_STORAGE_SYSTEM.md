# Permanent Storage System Architecture

## System Overview

The CSC IRC server implements a permanent storage system that ensures **zero data loss** even in catastrophic scenarios like unexpected power failure. This document describes the system architecture, recovery mechanisms, and operational characteristics.

### What Changed

Previously, the server used in-memory data structures with optional periodic snapshots. This architecture could lose recent changes if the server crashed between snapshots.

The permanent storage system ensures every state change is written to disk immediately using atomic operations before returning control to the IRC handler. This guarantees that:

- No operations are lost
- No partial data is written
- No data is corrupted even if power is cut mid-operation
- The server recovers completely on restart

### On-Demand Disk Reading

Oper credentials, active opers, and the client registry use `@property` methods in `server.py` that **read from disk on every access**. This means editing `opers.json` or `users.json` while the server is running takes effect immediately — no restart required.

```python
# server.py — these read from disk every time they're accessed:
@property
def oper_credentials(self):
    return self.storage.load_opers().get("credentials", {})

@property
def opers(self):
    return {nick.lower() for nick in self.storage.load_opers().get("active_opers", [])}

@property
def client_registry(self):
    return self.storage.load_users().get("users", {})
```

Channels and bans still use in-memory state (`ChannelManager`) loaded at startup and persisted atomically on every change.

## Architecture

### Data Storage Model

The system persists 5 JSON files in the server directory:

1. **`channels.json`** - All channels and their state
2. **`users.json`** - All registered users and their state
3. **`opers.json`** - All IRC operators and credentials
4. **`bans.json`** - Global and per-channel ban masks
5. **`history.json`** - Disconnection history (for WHOWAS)

Each file:
- Is valid, standalone JSON
- Can be restored independently
- Contains versioning information
- Is written atomically (all-or-nothing)

### JSON Schema

#### channels.json
```json
{
  "version": 1,
  "channels": {
    "#general": {
      "topic": "Welcome to CSC",
      "created_at": 1708054320.123,
      "modes": {"t": true, "n": true},
      "mode_params": {"k": null, "l": null},
      "members": ["alice", "bob"],
      "member_modes": {"alice": {"@": true}, "bob": {}},
      "ban_list": ["*!*@evil.com"]
    }
  }
}
```

#### users.json
```json
{
  "version": 1,
  "users": {
    "alice": {
      "user": "alice_user",
      "realname": "Alice Smith",
      "password": "hashed_password",
      "modes": ["+i", "+w"],
      "away": null,
      "channels": ["#general", "#dev"],
      "last_addr": "192.168.1.100",
      "registered_at": 1708054300.123
    }
  }
}
```

#### opers.json
```json
{
  "version": 1,
  "opers": {
    "admin": {
      "password": "hashed_password"
    }
  }
}
```

#### bans.json
```json
{
  "version": 1,
  "bans": {
    "global": ["*!*@banned.com"],
    "#general": ["*!*@evil.org"]
  }
}
```

#### history.json
```json
{
  "version": 1,
  "history": [
    {
      "nick": "alice",
      "event": "QUIT",
      "reason": "Bye!",
      "timestamp": 1708054350.456
    }
  ]
}
```

## Atomic Operations

The persistence system uses **atomic write pattern** to guarantee that files are never corrupted:

### Atomic Write Process

1. **Create temporary file** - Write new data to `{filename}.tmp`
2. **Flush to disk** - Call `fsync()` to ensure kernel writes to disk
3. **Atomic rename** - Rename `.tmp` to final filename (atomic operation on POSIX systems)
4. **Success** - Only after rename completes is the operation considered successful

This pattern ensures:
- Power failure during write doesn't corrupt the final file
- The `.tmp` file is lost, but the original remains intact
- After rename, either the old OR new file exists, never both, never neither
- No "half-written" states are possible

### Example Code Pattern

```python
def persist_channels(channels):
    temp_file = Path("channels.json.tmp")
    with open(temp_file, 'w') as f:
        json.dump({"version": 1, "channels": channels}, f)
        f.flush()
        os.fsync(f.fileno())

    # Atomic rename - guaranteed all-or-nothing
    temp_file.replace(Path("channels.json"))
```

## Recovery Process

### On Server Startup

1. **Load storage directory** - Check for all 5 JSON files
2. **Validate JSON** - Parse each file
3. **Handle corruption** - If parsing fails:
   - Rename corrupted file to `.corrupt.<timestamp>`
   - Recreate with empty/default data
   - Log the issue
4. **Restore state** - Load all data into memory structures
5. **Verify consistency** - Check bidirectional relationships
6. **Create defaults** - Ensure #general channel exists
7. **Ready for connections** - Server is now operational

### State Restoration

When the server loads `channels.json`, it:
1. Recreates all Channel objects
2. Recreates ChannelMember relationships
3. Restores channel topics and modes
4. Recreates ban lists
5. Re-establishes user ↔ channel bidirectional relationships

## Performance Impact

Every state-changing operation now includes a disk write. This makes certain operations slower:

- **User registration** - ~1ms (write to users.json)
- **Channel creation** - ~1ms (write to channels.json)
- **Mode changes** - ~1ms (write to channels.json or users.json)
- **Join/Part** - ~1ms (write to channels.json)

This is **intentional and acceptable**:
- Safety is more valuable than speed for state data
- Disk writes are sequential and fast
- Network I/O (IRC clients) dominates latency anyway
- Total overhead is <5% for typical IRC usage

### Optimization Opportunities

For future versions:
- Write coalescing - Batch multiple updates into single write
- Compression - gzip JSON files before writing
- Rotating history - Archive old history.json entries
- Sharding - Split large state files (many channels/users)

## File Locations

All files are stored in the server working directory:

```
/opt/csc/server/
├── channels.json         # Channel state
├── users.json           # User registrations
├── opers.json          # Operator credentials
├── bans.json           # Ban masks
├── history.json        # Disconnection history
├── channels.json.tmp   # Temporary during write
├── *.corrupt.* files   # Corrupted backups
└── server.py           # Main server code
```

## Troubleshooting

### Problem: Server Won't Start

**Symptoms**: Server crashes immediately on startup

**Causes**:
- Corrupted JSON file with syntax error
- Missing required fields in JSON
- File permissions prevent reading

**Solution**:
1. Check server logs for error messages
2. Look for `.corrupt.<timestamp>` files - indicates corruption
3. Verify file permissions: `ls -la /opt/csc/server/*.json`
4. Try deleting the corrupted file (server will recreate with defaults)

### Problem: Data Lost After Restart

**Symptoms**: Some users/channels gone after server restart

**Causes**:
- Handler didn't call persistence after state change
- Persistence failed silently (disk full, permission error)
- Corrupted JSON file was deleted instead of backed up

**Solution**:
1. Check server logs for persistence errors
2. Check disk space: `df -h`
3. Check file permissions: `ls -la /opt/csc/server/`
4. Look for `.corrupt.<timestamp>` files for recovery hints
5. Review server code to ensure handlers call persistence

### Problem: .tmp Files Remain

**Symptoms**: `channels.json.tmp`, `users.json.tmp` files accumulating

**Causes**:
- Server crashed during atomic rename
- Disk full preventing rename operation
- File permissions preventing rename

**Solution**:
1. These files are safe to delete (they're backup copies)
2. Address the underlying cause (restart, disk space, permissions)
3. Verify new operations complete and files are cleaned up

### Problem: Very Slow Server

**Symptoms**: IRC commands have noticeable lag

**Causes**:
- Disk is slow (USB drive, network mount)
- State files are very large (many users/channels)
- Disk I/O contention

**Solution**:
1. Check disk speed: `time dd if=/dev/zero of=testfile bs=1M count=100`
2. Check file sizes: `ls -lh /opt/csc/server/*.json`
3. Consider moving server directory to faster disk
4. Reduce history size or archive old entries

## Migration

### From Old System (Snapshots)

If migrating from the old snapshot-based system:

1. **Start new server** with persistent storage enabled
2. **Shutdown old server** cleanly
3. **Extract state** from `Server_data.json` snapshot
4. **Load into new system**:
   - Parse `session_snapshot` field
   - Convert to new JSON format
   - Write to new storage files
5. **Verify** all data transferred correctly
6. **Test** IRC operations work as expected
7. **Archive** old Server_data.json for reference

### Schema Versioning

The JSON files include a `version` field for future compatibility:

```json
{
  "version": 1,
  "data": {...}
}
```

If the file format changes in the future:
- Version field will be incremented
- Server can support multiple versions
- Migration code handles version upgrades
- Old files can be automatically converted

## Testing

The persistent storage system is verified by:

1. **test_persistence.py** - Merged test suite covering:
   - Complete lifecycle (multi-client sessions, restart, full state restore)
   - Handler persistence triggers (every state-changing command calls `_persist_session_data`)
   - Power failure resilience (simulated power cuts, corrupt/missing file recovery)
2. **POWER_FAILURE_VERIFICATION.md** - Manual verification checklist

Tests are run automatically by the cron test runner (`tests/run_tests.sh`). Check results in `tests/logs/test_persistence.log`.

## Future Improvements

### Schema Evolution

- Add new fields without breaking old versions
- Deprecation cycle for field removals
- Automatic migration scripts

### Performance Optimization

- Write coalescing for batch operations
- Compression for large state files
- Lazy loading for rarely-accessed data
- Rotating/archiving of history

### High Availability

- Replication to secondary server
- Multi-datacenter backup
- Cloud storage integration
- Event streaming (Kafka-like)

### Monitoring

- Metrics on write latency
- Alerts for persistence failures
- Corruption detection and recovery
- Audit logging of state changes

## References

- RFC 1459 - Internet Relay Chat Protocol
- POSIX atomic operations - `man fsync`, `man rename`
- JSON specification - https://www.json.org/
- Python json module - https://docs.python.org/3/library/json.html
- File I/O best practices - https://www.usenix.org/system/files/login/articles/10_019_082_paper.pdf
