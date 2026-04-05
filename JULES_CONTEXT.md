# Context for csc-service Elimination

## What Happened

1. **Mar 23, commit bd2ba070a**: csc-service monolith was dismantled into 14 modular packages
   - Strict one-class-per-file rule
   - Clean inheritance chain: Root → Log → Data → Version → Platform → Network → Services → Server → Loop
   - This was a GOOD architectural decision

2. **Mar 31, commit 670d1a2b7**: Queue federation workorder added code BACK to the dead csc-service package
   - This was a mistake - the implementation went to the wrong place
   - csc-service is deprecated and should not exist

3. **Now**: 233 imports from csc_service still exist across the codebase
   - The "dismantle" was never completed
   - csc-server-core imports from csc-service instead of the modular packages
   - Architectural debt blocking progress

## The 14 Modular Packages

See `CLAUDE.md` for full details, but packages are organized by layer:
- Layer 1-14 packages replacing the monolithic csc-service
- Each package has ONE class per file
- Each is independently installable

Key classes that MUST be found in the 14 packages:
- `MessageHandler` - message routing
- `FileHandler` - file upload handling
- `ChannelManager` - channel state
- `ChatBuffer` - message history
- `SERVER_NAME` constant
- Crypto functions (is_encrypted, decrypt, encrypt)

## Current Broken State

**csc-server-core (THE CURRENT SERVER) imports from deprecated csc-service:**

```python
from csc_service.server.server_message_handler import MessageHandler
from csc_service.server.server_file_handler import FileHandler
from csc_service.shared.channel import ChannelManager
from csc_service.shared.chat_buffer import ChatBuffer
from csc_service.shared.irc import SERVER_NAME
from csc_service.shared.crypto import is_encrypted, decrypt, encrypt
```

**These should be imported from the 14 modular packages instead.**

## What You Need to Do

**DO NOT refactor or redesign — just connect existing code to where it actually lives now.**

1. **Find where MessageHandler, FileHandler, ChannelManager, etc. are ACTUALLY defined**
   - They should be in the 14 packages (not in csc-service)
   - If they're only in csc-service, they need to be moved to the right package first

2. **Rewrite all 233 imports** to point to the real locations

3. **Delete csc-service/** directory

4. **Run tests** to confirm nothing broke

## How to Start

```bash
cd /c/csc/irc

# 1. Find all imports
grep -r "from csc_service" --include="*.py" packages/ | head -20

# 2. For the most common imports, find where they're defined
find packages/ -name "*.py" -exec grep -l "class MessageHandler" {} \;
find packages/ -name "*.py" -exec grep -l "class FileHandler" {} \;
find packages/ -name "*.py" -exec grep -l "class ChannelManager" {} \;
find packages/ -name "*.py" -exec grep -l "class ChatBuffer" {} \;

# 3. Once you know the new locations, bulk-rewrite imports
# (Use sed or Python script, don't do manually)
```

## Critical Invariants (Don't Break These)

From `CLAUDE.md`:
- Atomic Storage: All JSON updates use atomic pattern
- Disk is Source of Truth: Oper credentials read from disk on every access
- Case Sensitivity: IRC names normalized internally
- Mode System: Users/channels have mode flags
- Ban System: Global and per-channel bans
- Platform Detection: Runs on startup, persists to platform.json

**The new packages must preserve all of this.**

## Files to Check

- `CLAUDE.md` - Architecture docs, which packages do what
- `packages/csc-service/csc_service/server/server.py` - Current (broken) version using deprecated imports
- `packages/csc-server-core/csc_server_core/server.py` - The actual current server
- `irc/docs/` - Package documentation
- `tools/INDEX.txt` - Code maps showing what's in each package

## Success Criteria

1. No `from csc_service` imports remain in `packages/`
2. No `import csc_service` imports remain in `packages/`
3. `packages/csc-service/` directory is deleted
4. All tests pass
5. Fresh checkout + `pip install -e packages/*` works without errors

## Known Issues

- Queue federation code (commit 670d1a2b7) is in the deprecated csc-service
  - Don't try to port it now — that's a separate task
  - Just delete it with csc-service

- Some imports might be in unexpected places
  - Check `irc/packages/csc-server-core/` especially carefully
  - That's the actual current server, it has the most broken imports

## Questions to Answer First (Before Starting)

1. Where is `MessageHandler` actually defined in the 14 packages?
2. Where is `FileHandler` actually defined?
3. Where is `ChannelManager` actually defined?
4. Are they all properly exported from their package `__init__.py` files?
5. What are all the "from csc_service" imports? (`grep -r` will find them)

Answer these and you're 80% done. The rewriting is just mechanical after that.
