# Everything Plan — client-server-commander

All remaining features: version tracking everywhere, service ports from syscmdr-II, workflow/todolist system, channel modes, client-side command execution, ISOP, console auth, WALLOPS.

---

## Part 1: Version Tracking Service (new service module)

The `Version` class already exists in the inheritance chain (`server/version.py`) with `create_new_version()` and `restore_version()`. The `FileHandler` already calls `self.server.create_new_version()` before overwrites (line 167 of server_file_handler.py).

**What's missing:** There's no way to invoke versioning from the chatline. Port from syscmdr-II as a proper Service subclass.

### New file: `services/version_service.py`

```python
class Version(Service):
    # Wraps the server's existing Version methods as chatline-callable commands
    def create(self, filepath):     # AI do version create <path>
    def restore(self, filepath, version="latest"):  # AI do version restore <path> [version]
    def history(self, filepath):    # AI do version history <path>
    def list(self):                 # AI do version list — show all versioned files
```

Uses `self.server.create_new_version()` and `self.server.restore_version()` which already exist on the Server instance (inherited from Version class). No new versioning logic needed — just a service wrapper.

### Also: Make AI service commands versioned

In `server_message_handler.py` `_handle_service_via_chatline()`:
- Before executing destructive builtin commands (`delete_local`, `move_local`), call `self.server.create_new_version()` on affected files
- After `download_url_to_file` completes, version the target file

In `services/builtin_service.py`:
- `delete_local`: version the file before deleting
- `move_local`: version the source file before moving
- `download_url_to_file`: version the target if it exists before overwriting

---

## Part 2: Port Services from syscmdr-II

All need refactoring: standalone functions → Service subclass, `get_logger()` → `self.log()`.

### 2a. `services/todolist_service.py` (NEW)

```python
class Todolist(Service):
    def add(self, *args):           # AI do todolist add <prompt text>
    def list(self):                 # AI do todolist list
    def complete(self):             # AI do todolist complete (removes top item)
    def remove(self, index):        # AI do todolist remove <index>
    def default(self, *args):       # help
```

Data stored in `project_prompts.json` via the service's own `init_data()`.

### 2b. `services/backup_service.py` (NEW)

```python
class Backup(Service):
    def create(self, *paths):       # AI do backup create <path1> [path2...]
    def list(self):                 # AI do backup list
    def restore(self, archive, dest): # AI do backup restore <archive> <dest>
    def diff(self, archive, path):  # AI do backup diff <archive> <path>
    def default(self, *args):       # help
```

Uses `shutil`/`tarfile` (pure Python, no `tar` CLI dependency — works on Windows and Linux).

### 2c. `services/module_manager_service.py` (NEW)

```python
class Module_manager(Service):
    def list(self):                 # AI do module_manager list
    def read(self, name):           # AI do module_manager read <name>
    def create(self, name, content_b64): # AI do module_manager create <name> <base64>
    def rehash(self, *names):       # AI do module_manager rehash <module1> [module2...]
    def default(self, *args):       # help
```

### 2d. Replace `services/patch_service.py` (REWRITE)

The existing one depends on `import patch as patch_lib` (pip package) and a nonexistent `Version()` constructor. Rewrite to use the server's built-in versioning:

```python
class Patch(Service):
    def apply(self, filepath):      # AI do patch apply <diff_file>
    def revert(self, filepath):     # AI do patch revert <filepath> [version]
    def history(self, filepath):    # AI do patch history <filepath>
    def default(self, *args):       # help
```

Uses `subprocess.run(["patch", ...])` or pure Python unified diff application. Falls back gracefully if `patch` not available. Calls `self.server.create_new_version()` before applying.

---

## Part 3: Workflow System

### 3a. `services/workflow_service.py` (NEW)

The workflow operates through the chatline, not through direct API calls. Flow:

1. Human/AI adds a prompt to the todolist: `AI do todolist add "Refactor auth module"`
2. Human/AI triggers: `AI do workflow next`
3. Workflow service:
   - Pops next prompt from todolist
   - Broadcasts it to `#general` as a `ServiceBot` PRIVMSG: `[WORKFLOW] Task: "Refactor auth module" — AI agents, propose solutions.`
   - Sets workflow state to `awaiting_proposals`
   - AI agents see the message and respond with proposals on the chatline
4. Human or AI triggers: `AI do workflow approve` or `AI do workflow reject`
5. On approve:
   - Versions all affected files
   - Applies changes (via `<begin file>` or service commands)
   - Broadcasts result
6. On reject:
   - Reverts versioned files
   - Re-queues the prompt with failure note

```python
class Workflow(Service):
    def next(self):                 # Process next todolist item
    def status(self):               # Show current workflow state
    def approve(self):              # Accept proposed changes
    def reject(self):               # Reject and rollback
    def history(self):              # Show completed workflow items
    def default(self, *args):       # help
```

State persisted via `self.init_data()` → `workflow_data.json`.

---

## Part 4: Channel Modes (+m, +v, +t)

### 4a. `shared/channel.py` changes

Add to `Channel` class:
- `self.modes` already exists as `Set[str]` — use it for `m`, `t`
- Member modes already tracked (`info["modes"]`) — add `v` (voice)
- `can_speak(nick)`: returns True if channel not +m, or nick has +v or +o
- `can_set_topic(nick)`: returns True if channel not +t, or nick has +o

### 4b. `server/server_message_handler.py` changes

Update `_handle_mode()`:
- Support `MODE #channel +m` / `-m` (moderated)
- Support `MODE #channel +t` / `-t` (topic lock)
- Support `MODE #channel +v <nick>` / `-v <nick>` (voice)
- Require chanop or oper for all channel mode changes

Update `_handle_privmsg()`:
- Check `channel.can_speak(nick)` before allowing messages
- If can't speak, send `ERR_CANNOTSENDTOCHAN`

Update `_handle_topic()`:
- Check `channel.can_set_topic(nick)` before allowing topic changes

### 4c. `client/client.py` changes

Update `_handle_irc_line()` MODE handler to show mode changes properly.

---

## Part 5: Client-Side Command Execution

Any client that imports `service.py` can execute commands locally. Channel messages starting with `<nick> AI <token> <class> <method>` execute on the target client's machine.

### 5a. `client/client.py` changes

Add to `_handle_privmsg_recv()`:
- Parse incoming PRIVMSG text for `<own_nick> AI <token> <class> <method> [args]`
- Parse incoming PRIVMSG text for `<own_nick> <begin file=...>`
- Auth check before executing:
  - Sender has +o in any shared channel, OR
  - Sender is an ircop (query via ISOP), OR
  - Sender is the server itself (prefix contains `@csc-server`)
- If authorized: execute locally via `self.handle_command()` (Client inherits from Network→Version→...→Service which has `handle_command`)
- Send result back to the channel as PRIVMSG

### 5b. Track channel ops on client side

Client needs to track who has +o in channels it's in:
- `self.channel_ops = {}` — `{channel: set(nicks_with_op)}`
- Parse NAMES replies (353) to extract `@nick` prefixes
- Track MODE +o/-o changes
- Track JOIN/PART/QUIT to remove nicks

### 5c. `gemini/gemini.py` and `claude/claude.py` changes

Same as client — add nick-prefixed command parsing to `handle_server_message()` so AI clients can also receive and execute commands addressed to them.

---

## Part 6: ISOP Command

### 6a. `server/server_message_handler.py`

Add `ISOP` to post-registration commands:

```python
def _handle_isop(self, msg, addr):
    """ISOP <nick> — returns whether nick is an IRC operator."""
    nick = self._get_nick(addr)
    target = msg.params[0] if msg.params else nick
    is_oper = target in self.server.opers
    reply = f":{SERVER_NAME} NOTICE {nick} :ISOP {target} {'YES' if is_oper else 'NO'}\r\n"
    self.server.sock_send(reply.encode(), addr)
```

### 6b. Client-side ISOP query for auth

When client receives a nick-prefixed command and needs to check ircop status:
- Send `ISOP <sender_nick>` to server
- Wait for NOTICE reply with result
- Cache ircop status briefly (TTL ~30s)

---

## Part 7: Server Console Authentication

### 7a. `server/server_console.py` changes

Wrap `run_loop()` with authentication:
- On startup, prompt: `Console login — Nick: ` then `Password: `
- Validate against `oper_credentials`
- If authenticated: full access (existing behavior)
- If not authenticated: read-only commands only (`/clients`, `/channels`, `/help`)
- Admin commands (`/kick`, `/oper`, `/set motd`, free-text broadcast) require oper auth
- Track console nick for WALLOPS

### 7b. Console acts like a client

Console sends messages as `ServerAdmin!admin@csc-server` (already does this). After auth, use the oper's nick instead.

---

## Part 8: WALLOPS

### 8a. `server/server_message_handler.py`

Add WALLOPS support:
- `_handle_wallops(msg, addr)`: oper-only, broadcasts to all opers
- All oper activity auto-broadcasts WALLOPS:
  - OPER auth success
  - KICK
  - KILL
  - MODE changes on channels
  - Console admin actions

### 8b. Server helper method

In `server/server.py`:
```python
def send_wallops(self, message):
    """Send a WALLOPS message to all connected opers."""
    wallops_msg = f":{SERVER_NAME} WALLOPS :{message}\r\n"
    for addr, info in list(self.clients.items()):
        nick = info.get("name")
        if nick and nick in self.opers:
            self.sock_send(wallops_msg.encode(), addr)
```

### 8c. Client-side WALLOPS display

In `client/client.py` `_handle_irc_line()`:
- Handle `WALLOPS` command: `print(f"[WALLOPS] {text}")`

---

## Part 9: Sync Copies

After all changes to shared/ files, copy to:
- `server/`, `client/`, `gemini/`, `run/gemini/` (Windows symlink workaround)
- Copy updated `client.py` to `gemini/client.py` and `claude/client.py`

---

## Files Modified/Created

| # | File | Action |
|---|------|--------|
| 1 | `services/version_service.py` | NEW — version commands via chatline |
| 2 | `services/todolist_service.py` | NEW — prompt queue |
| 3 | `services/backup_service.py` | NEW — tar.gz backups (pure Python) |
| 4 | `services/module_manager_service.py` | NEW — dynamic module management |
| 5 | `services/workflow_service.py` | NEW — AI-collaborative workflow |
| 6 | `services/patch_service.py` | REWRITE — use built-in versioning |
| 7 | `services/builtin_service.py` | MODIFY — version before destructive ops |
| 8 | `shared/channel.py` | MODIFY — add +m/+v/+t mode support |
| 9 | `server/server_message_handler.py` | MODIFY — modes, ISOP, WALLOPS, version before AI commands |
| 10 | `server/server.py` | MODIFY — add send_wallops() |
| 11 | `server/server_console.py` | MODIFY — add auth, WALLOPS |
| 12 | `client/client.py` | MODIFY — nick-prefixed exec, op tracking, WALLOPS display, ISOP |
| 13 | `gemini/gemini.py` | MODIFY — nick-prefixed exec |
| 14 | `claude/claude.py` | MODIFY — nick-prefixed exec |
| 15 | Various copies | SYNC — Windows symlink workaround |

## Verification

1. Start server → verify console asks for auth, `/help` works unauthenticated, `/kick` requires auth
2. Connect two human clients → verify +m, +v, +t channel modes work
3. `AI do version create <file>` → verify backup in versions/ dir
4. `AI do version restore <file>` → verify file reverted
5. `AI do todolist add "test task"` → verify stored in JSON
6. `AI do workflow next` → verify task broadcast to #general
7. `AI do backup create services` → verify tarball created
8. Send `ISOP admin` → verify YES/NO reply
9. Nick-prefixed command: `Alice AI do builtin echo hello` (sent by an op) → verify Alice executes locally and replies
10. OPER auth → verify WALLOPS broadcast to all opers
11. Connect Gemini/Claude → verify they can receive and execute nick-prefixed commands
12. `/kick user` from console → verify WALLOPS sent, user removed
