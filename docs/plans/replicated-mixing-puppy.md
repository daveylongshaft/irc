# Chat Buffer Logging & Replay

## Goal
Log all PRIVMSG/NOTICE messages server-side by channel or PM pair, trim to 100KB, and replay on request via `BUFFER <target>` command + auto-replay on JOIN.

## New File

### `shared/chat_buffer.py` — ChatBuffer class
- Composed into Server (like FileHandler), not inherited
- One `.log` file per channel or PM pair in `buffers/` directory
- Channel key: `chan_general.log` for `#general`
- PM key: `alice_bob.log` (nicks sorted alphabetically)
- Per-file `threading.Lock` for thread safety (server uses worker threads per packet)
- **Methods:**
  - `append(target, sender_nick, command, text)` — timestamped line, appends to file, trims if >100KB (keep newest ~75KB at newline boundary)
  - `read(target, sender_nick=None)` — returns list of log lines
  - `_trim_if_needed(filepath)` — truncate from front
- Uses Log class pattern: `open(filepath, "a")` with timestamps

## Modified Files

### `server/server.py`
- Import `ChatBuffer`
- Add `self.chat_buffer = ChatBuffer()` in `__init__` after channel_manager

### `server/server_message_handler.py`
1. **Hook `_handle_privmsg`** — after broadcast/send, call `self.server.chat_buffer.append(target, nick, "PRIVMSG", text)` for both channel and PM messages
2. **Hook `_handle_notice`** — same pattern
3. **Add `"BUFFER": self._handle_buffer`** to post_reg dispatch dict
4. **`_handle_buffer(msg, addr)`** — validates params + channel membership, calls `_send_buffer_replay`
5. **`_send_buffer_replay(addr, nick, target)`** — reads buffer, sends each line as `NOTICE` from server with `[BUFFER]` prefix, with start/end markers
6. **Hook `_handle_join`** — after names list, call `_send_buffer_replay` for auto-replay

### `client/client.py` (+ copies in gemini/, claude/, server/, run/gemini/)
1. Add `/buffer [target]` command in `process_command` — sends `BUFFER <target>\r\n`
2. Improve `_handle_notice_recv` — detect `[BUFFER]` prefix, print with distinct indented format
3. Add help text for `/buffer`

## Replay Format
Buffer lines sent as NOTICE to avoid auto-reply loops:
```
-csc-server- [BUFFER] -- Start of buffer replay for #general (42 lines) --
-csc-server- [BUFFER] [2025-01-15 14:30:00] :alice PRIVMSG #general :hello
-csc-server- [BUFFER] -- End of buffer replay for #general --
```

## Verification
1. Start server, connect 2+ clients
2. Send messages on `#general`, verify `buffers/chan_general.log` appears with content
3. Send PMs between clients, verify `buffers/alice_bob.log` appears
4. Disconnect and reconnect a client — on JOIN `#general`, verify buffer replay appears
5. Run `/buffer #general` manually — verify replay output
6. Write >100KB of messages, verify file gets trimmed to ~75KB
7. Run existing test suite: `py -m pytest tests/ --ignore=tests/test_gemini.py`
