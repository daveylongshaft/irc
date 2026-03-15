# Plan: Client-Side Service Execution & File Upload Handling

## Goal
Client executes `AI t c m a` commands and accepts `<begin file>/<end file>` uploads locally when prefixed with the client's nick. Works on all client interfaces (human, Gemini, Claude). Notifies but requires no user/agent action.

## Files to Create

### 1. `client/client_service_handler.py`
- Wraps `Service.handle_command()` for client-side execution
- `execute(command_text, source_nick)` → parses AI command, delegates to Service.handle_command(), returns `(token, result)`
- Creates a single `Service` instance, passing Client as `server_instance`

### 2. `client/client_file_handler.py`
- Adapted from `server/server_file_handler.py`, keyed by sender nick instead of addr
- `start_session(sender_nick, text)` - validates path, starts buffering
- `process_chunk(sender_nick, text)` - buffers content
- `complete_session(sender_nick)` - validates, versions, writes
- `has_active_session(sender_nick)` - check if sender has active upload
- Same security: root confinement + core file protection via `secret.get_known_core_files()`

## Files to Modify

### 3. `client/main.py`, `gemini/main.py`, `claude/main.py`
Add `server/` dir and CSC project root to `sys.path` so `from service import Service` and `services.*` imports work.

### 4. `client/client.py`
- Import `ClientServiceHandler` and `ClientFileHandler`
- In `__init__`: set `self.project_root_dir` to CSC root, instantiate handlers
- Rewrite `_handle_privmsg_recv()`:
  - First check: sender has active file session → route to file handler
  - Nick-prefixed `AI ...` → execute locally via service handler, send result to channel
  - Nick-prefixed `<begin file=...>` → start local file session
  - Print `[LOCAL]` notifications for both cases
- Add `_handle_local_file_session_line(sender, text, target)` method

### 5. `gemini/gemini.py` and `claude/claude.py`
- Remove nick-prefixed command forwarding from `handle_server_message()` — inherited `_handle_privmsg_recv()` handles it now

### 6. `README.md`
- Add section documenting client-side service execution and file upload features
- Update startup section with examples of the encrypted system using the translator app

## Verification
- Run existing tests: `python -m pytest tests/`
- Manual test: start server + client, send `ClientName AI do builtin echo hello` — should execute locally and show result
- Manual test: send `ClientName <begin file="temp/test.txt">` + content + `<end file>` — should write file locally

## Agent Usage (Cost Priority)
1. **Haiku agents** (cheapest) for all file I/O, search, test, doc work:
   - `file-writer` for creating new files
   - `file-editor` for modifying existing files
   - `test-runner` for running tests
   - `doc-writer` for README updates
   - `explorer`, `searcher`, `code-reader` for any lookup
2. **Sonnet** for any non-haiku agent reasoning/orchestration
3. **Opus** only if sonnet fails — never use by default
