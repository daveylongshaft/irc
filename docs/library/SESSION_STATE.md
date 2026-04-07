# Current Session State

**Last Updated**: 2026-02-15
**Status**: Ready for next session

---

## What Was Just Done

Created/updated documentation files to help future Claude instances:
- ✅ Analyzed codebase architecture
- ✅ Updated `claude.md` - Guides on using `prompts` command for task management
- ✅ Documented crash recovery pattern (mark BEFORE each action with `[NEXT]`)

---

## Project Quick Facts

**CSC** = IRC-based multi-AI orchestration system
- Server: `/opt/csc/packages/csc-server/` (handles channels, users, persistence)
- Clients: Claude, Gemini, ChatGPT connect as IRC clients
- Core: `/opt/csc/packages/csc-shared/` (IRC protocol library)
- Storage: Atomic JSON writes (channels.json, users.json, opers.json, bans.json, history.json)

**Key invariant**: All state changes written to disk immediately - zero data loss guarantee

---

## Common Commands (Copy-Paste Ready)

```bash
# Check task queue
prompts list wip          # Current task
prompts list ready        # Next tasks
prompts list done         # Completed

# Start/resume work
prompts move <filename> wip
prompts read <filename>

# Run system
csc-server                # Terminal 1
csc-client                # Terminal 2
csc-claude                # Terminal 3 (etc)

# Run tests
python -m pytest tests/ -v
python -m pytest tests/test_server_irc.py -v
python -m pytest tests/test_power_failure_resilience.py -v
```

---

## What's in the Codebase

| Package | Purpose |
|---------|---------|
| `csc-shared` | IRC protocol library (Message, Channel, User classes) |
| `csc-server` | Main server (server.py, message handlers, storage) |
| `csc-client` | Human CLI client |
| `csc-claude` | Claude AI client |
| `csc-gemini` | Gemini AI client |
| `csc-chatgpt` | ChatGPT AI client |
| `csc-bridge` | IRC protocol bridge proxy |

---

## Important Files to Know About

- `PERMANENT_STORAGE_SYSTEM.md` - How atomic writes work
- `POWER_FAILURE_VERIFICATION.md` - Storage resilience tests
- `prompts/README.md` - Details on task queue system
- `prompts/PROMPTS_CLI_QUICKREF.md` - `prompts` command examples

---

## Known Patterns

1. **IRC Handlers** - All commands in `server_message_handler.py`
2. **Channel/User State** - In-memory dicts + JSON storage (atomic writes)
3. **Message Flow** - Client → Server → Route to Channel → Broadcast
4. **Testing** - Pytest tests in `/opt/csc/tests/`

---

## Next Session Checklist

- [ ] `prompts list wip` - Check for active task
- [ ] `prompts read <filename>` - See work log and where you left off
- [ ] If wip is empty: `prompts list ready` → pick task → `prompts move <filename> wip`
- [ ] Remember to mark `[NEXT]` BEFORE each action for crash recovery

---

## Notes for Future Work

- Storage system is critical to this project (atomic writes, zero-loss guarantee)
- All packages are pip-installable and located in `/opt/csc/packages/`
- Tests are authoritative on behavior
- Use lightweight models: Haiku for exploration, Sonnet for implementation
