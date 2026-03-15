# Power Failure Verification Checklist

This document provides a comprehensive verification checklist for testing the CSC IRC server's power failure resilience. The persistent storage system is designed to survive unexpected power loss at any point during operation with zero data loss.

## Overview

The CSC server uses atomic write operations and immediate persistence to ensure that all state changes are safely written to disk before returning control to the handler. This architecture allows the server to be abruptly terminated at any moment (simulating power failure) and restart with complete state restoration.

## Test Categories

### 1. Data Integrity

Verify that all JSON files remain valid and consistent after any operation.

#### JSON File Validity
- [ ] `channels.json` is valid JSON after every state change
- [ ] `users.json` is valid JSON after every state change
- [ ] `opers.json` is valid JSON after every state change
- [ ] `bans.json` is valid JSON after every state change
- [ ] `history.json` is valid JSON after every state change
- [ ] No `.tmp` files remain after operations complete
- [ ] All files contain a valid `version` field

#### Atomic Operations Working
- [ ] No partial writes detected in any JSON file
- [ ] Corrupting a file during write does not affect other files
- [ ] Server uses temp file + fsync + rename pattern
- [ ] Failed writes do not corrupt existing data
- [ ] Simultaneous state changes do not create race conditions

#### Count Consistency
- [ ] Channel count in `channels.json` matches actual channel list
- [ ] User count in `users.json` matches actual registered users
- [ ] Ban count in `bans.json` matches per-channel ban lists in `channels.json`
- [ ] Oper count in `opers.json` matches active operators
- [ ] History count in `history.json` does not exceed max (100 entries)

#### Data Completeness
- [ ] All required fields present in channel records
- [ ] All required fields present in user records
- [ ] Channel membership data is bidirectional (user knows channel, channel knows user)
- [ ] Ban masks stored in both `bans.json` and channel `ban_list`
- [ ] Timestamps are valid float values

### 2. Recovery After Power Failure

Verify that the server can restart and fully restore state after simulated power loss.

#### Server Startup
- [ ] Server starts successfully after abrupt termination
- [ ] All JSON files are loaded without errors
- [ ] Corrupt files are renamed to `.corrupt.<timestamp>` and replaced
- [ ] Missing files are recreated with empty defaults
- [ ] Default #general channel is created if no channels exist

#### Client Session Restoration
- [ ] All registered users are restored from `users.json`
- [ ] User nicks are restored correctly
- [ ] User credentials (user, realname, password) are restored
- [ ] Client addresses (`last_addr`) are restored for reconnection
- [ ] Last seen timestamps are preserved

#### Channel State Restoration
- [ ] All channels from `channels.json` are recreated
- [ ] Channel topics are restored correctly
- [ ] Channel modes (t, n, m, i, s, p) are restored
- [ ] Channel mode parameters (k, l) are restored
- [ ] Channel creation timestamps are preserved
- [ ] Channel membership lists are complete

#### Membership Restoration
- [ ] Users remember which channels they were in
- [ ] Channels remember which users were members
- [ ] User modes within channels (@, +) are restored
- [ ] NAMES command shows correct member list after restart
- [ ] WHOIS shows correct channels for users

#### Mode Restoration
- [ ] User modes (+i, +w, +o, +a) are restored
- [ ] Channel modes are applied correctly after restart
- [ ] Away status (+a) and messages are restored
- [ ] Operator status (+o) is restored from `opers.json`
- [ ] MODE queries return correct values after restart

#### Ban Persistence
- [ ] Channel ban lists are restored from `bans.json`
- [ ] Ban masks match expected patterns
- [ ] Bans still apply to matching users after restart
- [ ] MODE #channel +b shows correct ban list
- [ ] Banned users cannot join channels after restart

#### Operator Persistence
- [ ] Oper credentials are loaded from `opers.json`
- [ ] Active operators are restored to `server.opers` set
- [ ] Operator commands work immediately after restart
- [ ] OPER command authentication still works
- [ ] Non-operators cannot use privileged commands

#### Disconnection History
- [ ] QUIT events are recorded in `history.json`
- [ ] KILL events are recorded in `history.json`
- [ ] WHOWAS returns correct information after restart
- [ ] Disconnection timestamps are preserved
- [ ] Quit reasons are preserved
- [ ] History does not exceed 100 entries

### 3. Edge Cases

Test unusual or extreme scenarios to ensure robustness.

#### Empty Server Scenarios
- [ ] Empty server (no users, no channels) restarts cleanly
- [ ] Default #general channel is created on empty restart
- [ ] Empty JSON files do not cause errors
- [ ] First user registration works after empty restart

#### High Load Scenarios
- [ ] Many users (50+) are restored correctly
- [ ] Many channels (20+) are restored correctly
- [ ] Large ban lists (10+ per channel) are restored
- [ ] Large disconnection history (100 entries) is restored
- [ ] Performance is acceptable with large state files

#### Corrupt Data Scenarios
- [ ] Corrupt `channels.json` is handled gracefully
- [ ] Corrupt `users.json` is handled gracefully
- [ ] Corrupt `opers.json` is handled gracefully
- [ ] Corrupt `bans.json` is handled gracefully
- [ ] Corrupt `history.json` is handled gracefully
- [ ] Multiple corrupt files do not prevent startup
- [ ] Corrupt files are backed up before replacement

#### Missing File Scenarios
- [ ] Missing `channels.json` recreated with defaults
- [ ] Missing `users.json` recreated with defaults
- [ ] Missing `opers.json` recreated with defaults
- [ ] Missing `bans.json` recreated with defaults
- [ ] Missing `history.json` recreated with defaults
- [ ] All missing files do not prevent startup

#### Simultaneous Operations
- [ ] Multiple JOIN commands in quick succession persist correctly
- [ ] Rapid MODE changes persist correctly
- [ ] Concurrent user registrations persist correctly
- [ ] Multiple channels created simultaneously persist correctly
- [ ] Race conditions do not cause data loss

#### Partial Migration
- [ ] Old `Server_data.json` with `session_snapshot` is migrated
- [ ] Migration preserves all user data
- [ ] Migration preserves all channel data
- [ ] Old snapshot file is not corrupted during migration
- [ ] Server can run with both old and new formats

### 4. Client State Restoration

Verify that IRC clients can restore their state across server restarts.

#### Client State Files
- [ ] Client state file `{name}_state.json` is created
- [ ] State file uses atomic write (temp + rename) pattern
- [ ] State file is valid JSON
- [ ] State file contains nick, modes, and channels
- [ ] Corrupt state files are ignored gracefully

#### Client Reconnection
- [ ] Client loads state file on startup
- [ ] Client restores nick after reconnection
- [ ] Client restores user modes after reconnection
- [ ] Client rejoins channels after reconnection
- [ ] Client state persists across multiple restarts

#### Mode Preservation
- [ ] User modes (+i, +w) are saved to state file
- [ ] Modes are reapplied after client restart
- [ ] MODE queries show correct modes after restore
- [ ] Away status is preserved in state file
- [ ] Operator status triggers state save

#### Channel Membership Preservation
- [ ] Joined channels are saved to state file
- [ ] Client rejoins all channels after restart
- [ ] Channel list is updated when JOIN/PART occurs
- [ ] NAMES shows client in correct channels after restore
- [ ] Empty channel list is handled correctly

#### State File Lifecycle
- [ ] State file is created on first connection
- [ ] State file is updated after nick change
- [ ] State file is updated after mode change
- [ ] State file is updated after JOIN/PART
- [ ] State file persists after client exit

## Testing Methodology

### Manual Testing Procedure

1. **Setup**: Start fresh server, clear all JSON files
2. **Populate**: Register users, create channels, set modes, add bans
3. **Verify Pre-Crash**: Use IRC commands to verify current state
4. **Simulate Crash**: Kill server process (SIGKILL or Ctrl+C)
5. **Restart**: Start server again
6. **Verify Post-Restart**: Use IRC commands to verify restored state
7. **Compare**: Ensure all data matches pre-crash state

### Automated Testing

The following test files provide comprehensive automated verification:

- `/opt/csc/tests/test_power_failure_resilience.py`
  - 13 test cases covering user/channel/mode/ban restoration
  - Simulates power failure by creating fresh server instances
  - Verifies atomic writes and JSON validity

- `/opt/csc/tests/test_complete_persistence.py`
  - Integration tests for full IRC sessions
  - Multi-client scenarios with complex state
  - Multiple consecutive restart tests

- `/opt/csc/tests/test_handler_persistence.py`
  - Verifies every IRC command triggers persistence
  - Tests all state-changing handlers (NICK, JOIN, MODE, etc.)
  - Ensures no operations are lost

### Running Automated Tests

```bash
# Run all persistence tests
cd /opt/csc
python -m pytest tests/test_power_failure_resilience.py -v
python -m pytest tests/test_complete_persistence.py -v
python -m pytest tests/test_handler_persistence.py -v

# Run specific test case
python -m pytest tests/test_power_failure_resilience.py::TestPowerFailure::test_01_user_connects_power_cut -v
```

## Expected Results

### Successful Verification

A fully resilient system should pass all checks with these outcomes:

- **Zero data loss**: All state changes made before crash are preserved
- **Zero corruption**: No invalid JSON files after any crash scenario
- **Zero crashes**: Server starts successfully after any failure scenario
- **Complete restoration**: All users, channels, modes, bans, history restored
- **Functional server**: All IRC commands work immediately after restart
- **Client reconnection**: Clients can reconnect and resume sessions

### Failure Indicators

The following indicate problems requiring investigation:

- `.tmp` files remaining after operations
- Invalid JSON in any data file
- Missing data after restart (channels, users, modes, etc.)
- Server fails to start after crash
- Partial data restoration (some users missing, some channels gone)
- Different state before/after restart

## Troubleshooting Failed Verification

### If JSON Files Are Corrupt

1. Check system logs for disk errors
2. Verify filesystem supports atomic rename (`os.replace`)
3. Check that `fsync()` is working correctly
4. Verify storage directory has correct permissions
5. Look for `.corrupt.<timestamp>` backup files

### If Data Is Missing After Restart

1. Verify `_persist_session_data()` is called after state changes
2. Check that handlers call persistence after operations
3. Verify `persist_all()` returns True (not False)
4. Check system logs for write errors
5. Verify storage directory exists and is writable

### If Server Crashes On Restart

1. Check for JSON syntax errors in data files
2. Verify schema version compatibility
3. Check for missing required fields in records
4. Verify ChannelManager initialization
5. Look for exceptions in server logs

### If Counts Don't Match

1. Verify bidirectional relationships (user knows channel, channel knows user)
2. Check for orphaned records in JSON files
3. Verify cleanup happens on QUIT/PART/KICK
4. Check for duplicate entries
5. Verify array/set conversions are correct

## Continuous Verification

### Development Workflow

1. Run automated tests before committing changes
2. Add new test cases for new state-changing features
3. Verify atomic write pattern in all new persistence code
4. Test manual crash scenarios during development
5. Monitor test coverage for persistence paths

### Production Monitoring

1. Monitor for `.corrupt` backup files (indicates corruption)
2. Check JSON file sizes for unusual growth
3. Monitor server startup time (slow = large state files)
4. Log persistence failures and investigate
5. Regular backups of `/opt/csc/server/` directory

## Certification

To certify that the CSC persistent storage system is power failure resilient:

- [ ] All automated tests pass
- [ ] All manual verification checks pass
- [ ] Edge cases tested and verified
- [ ] Production crash scenarios tested
- [ ] Documentation reviewed and accurate
- [ ] Team trained on troubleshooting procedures

**Certified by**: _______________
**Date**: _______________
**Test Version**: _______________

## References

- [PERMANENT_STORAGE_SYSTEM.md](PERMANENT_STORAGE_SYSTEM.md) - Complete architecture documentation
- [PERMANENT_STORAGE_ARCHITECTURE.md](PERMANENT_STORAGE_ARCHITECTURE.md) - Technical architecture details
- RFC 1459 - Internet Relay Chat Protocol specification
- `server/storage.py` - PersistentStorageManager implementation
