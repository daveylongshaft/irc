# FTPD-IRCD Plan

## Goal

Provide a complete IRC operator interface to the FTP virtual filesystem so an IRCop can browse, fetch, upload, rename, delete, and DCC-share files without using a standalone FTP client.

Primary user-facing flows:

- `/ftp cwd /path/to/`
- `/ftp ls`
- `/ftp get /path/to/file.ext`
- `/ftp upload file.ext ftp:/path/to/`
- `/ftp rnfr /path/from`
- `/ftp rnto /path/to`
- `/ftp del /path/to/file`
- `/dcc send nick ftp:/path/to/file.ext`
- Accept a standard DCC file send in `csc-client` and upload it directly into the FTP virtual filesystem

Access requirement:

- IRCops only

Success condition:

- `csc-client` can manage the FTP virtual filesystem entirely over IRC commands and DCC
- Existing FTPD state remains authoritative
- Changes continue to fan out through the existing FTP master/slave sync path

## Existing System To Build On

The codebase already has most of the substrate needed. The plan should extend that instead of introducing a second file-management stack.

Relevant pieces:

- Server VFS command handler: `packages/csc-server-core/csc_server_core/handlers/vfs.py`
- Server side transfer socket: `packages/csc-server-core/csc_server_core/vfs_data_conn.py`
- Client VFS command implementation: `packages/csc-clients/csc_clients/client/client.py`
- FTP virtual filesystem abstraction: `packages/csc-ftpd/csc_ftpd/ftp_virtual_fs.py`
- FTP master index and sync: `packages/csc-ftpd/csc_ftpd/ftp_master.py`
- FTP command semantics already implemented in FTPD: `packages/csc-ftpd/csc_ftpd/ftp_handler.py`

Important current behavior:

- `VFS` already supports `LIST`, `CWD`, `CAT`, `RNFR`, `RNTO`, `DEL`, `ENCRYPT`, `DECRYPT`
- `VFS` already uses a PRET-style TCP side channel for upload/download/list data
- `VFS` already triggers FTP slave sync after mutating operations
- Client code already knows how to consume `NOTICE :VFS PRET ...`

Main gap:

- There is no cohesive `/ftp` operator UX
- There is no DCC bridge between IRC file transfer semantics and the FTP virtual filesystem
- The current access gate is broader than requested

## Design Direction

Do not build a parallel "FTP over IRC" subsystem. Make `/ftp` an IRCop-facing command layer over the existing VFS/FTPD path.

Recommended architecture:

1. Keep FTPD and the virtual filesystem as the source of truth.
2. Treat the current VFS server handler as the transport/control layer.
3. Add an IRC-facing `/ftp` command family in the client as the primary UX.
4. Extend the server handler where needed, but do not bypass `ftp_virtual_fs`.
5. Add DCC send/receive integration in the client, with explicit handoff to the VFS transfer path.

This preserves the current layering:

- `data`: path metadata, permissions, state persistence
- `log`: audit and diagnostics for file operations and DCC actions
- `network`: IRC, DCC, PRET/VFS transfer sockets
- `platform`: filesystem and socket portability helpers if needed

## Command Surface

### IRC commands

Add a first-class `/ftp` command family in `csc-client`.

Recommended subcommands:

- `/ftp pwd`
- `/ftp cwd <path>`
- `/ftp ls [path]`
- `/ftp get <ftp-path> [local-path]`
- `/ftp upload <local-path> <ftp-dir-or-path>`
- `/ftp rnfr <ftp-path>`
- `/ftp rnto <ftp-path>`
- `/ftp mv <from> <to>`
- `/ftp del <ftp-path>`
- `/ftp mkdir <ftp-path>` if directory creation support is added
- `/ftp help`

Implementation note:

- Keep `/vfs` as the protocol-level/internal command if that reduces churn.
- Expose `/ftp` as the operator UX.
- `/ftp` can initially map onto the existing `VFS` verbs and later gain dedicated server verbs only where the current interface is too awkward.

### DCC semantics

Two DCC workflows are needed.

Outbound from VFS to another IRC user:

- `/dcc send nick ftp:/path/to/file.ext`
- If the source begins with `ftp:`, `csc-client` resolves it through the VFS/FTPD path and advertises a normal DCC SEND to the peer.
- The recipient should see a standard DCC file offer.

Inbound from another IRC user into VFS:

- When `csc-client` receives a standard DCC SEND and the operator accepts it, the client should be able to target the FTP virtual filesystem directly.
- Preferred UX:
  - auto-route into a configured FTP inbox path, or
  - support an explicit accept target command such as `/dcc accept nick file.ext ftp:/incoming/`
- The received bytes should stream directly into the VFS upload path without forcing an intermediate manual FTP step.

## Authorization Model

Your requirement is IRCops-only access.

Plan:

1. Tighten server-side authorization in the VFS handler so mutating and read operations require oper privileges.
2. Do not rely on client-side hiding alone.
3. Log every FTP-over-IRC action with nick, server, verb, and target path.
4. Reject attempts from non-opers with a clear notice.

Open compatibility choice:

- Either keep legacy NickServ-identified access behind a config flag for backward compatibility, or
- enforce IRCop-only immediately and migrate existing users

Recommended default:

- IRCop-only for the new `/ftp` surface
- leave `/vfs` compatibility behavior configurable during transition

## Server Work Plan

### 1. Normalize the server command boundary

Review whether `VFS` should stay as the wire command or whether an `FTP` alias should be added server-side.

Recommendation:

- Keep `VFS` as the underlying server handler for now
- Add a thin `FTP` alias only if that materially improves observability or permission routing

Reasons:

- Lower protocol churn
- Reuses the existing PRET flow
- Less risk to current users

### 2. Harden access control

In `packages/csc-server-core/csc_server_core/handlers/vfs.py`:

- Change the gate from "NickServ identified or oper" to an explicit oper-capable permission check for the new management surface
- Centralize the auth check instead of repeating it per verb
- Emit structured logs for allow/deny decisions

### 3. Extend verbs only where necessary

Existing verbs already cover most of the requested scope:

- `LIST` for `ls`
- `CWD` for `cwd`
- upload/download via PRET data connection
- `RNFR` and `RNTO` for rename/move
- `DEL` for delete

Likely additions:

- `PWD` convenience verb if current client state is too implicit
- `MKDIR` if directory creation is required
- Better server notices/errors so IRC UX is usable without reading internals

### 4. Preserve FTP sync correctness

Any mutating operation must continue using the current FTP master/slave propagation path.

Checks:

- rename still updates the virtual FS view correctly
- upload/delete still trigger the current slave sync function
- no new direct filesystem writes are introduced outside the FTPD/VFS layer

### 5. Add auditing

Use the logging package, not ad hoc prints.

Log events:

- browse/list requests
- downloads
- uploads
- rename source/target
- delete
- outbound DCC send of VFS-backed content
- inbound DCC receipt routed into VFS

## Client Work Plan

### 1. Add `/ftp` command family

In `packages/csc-clients/csc_clients/client/client.py`:

- Add a top-level `/ftp` dispatcher
- Map user-friendly verbs onto the existing VFS transport
- Keep a client-side current working directory for FTP paths
- Normalize `ftp:/...` and relative paths against that cwd

Command mapping:

- `/ftp cwd /a/b` -> VFS `CWD`
- `/ftp ls` -> VFS `LIST` on current directory
- `/ftp get ftp:/x/y` -> PRET download
- `/ftp upload local ftp:/x/` -> PRET upload
- `/ftp rnfr` and `/ftp rnto` -> existing rename flow
- `/ftp mv a b` -> client convenience wrapper over `RNFR` + `RNTO`

### 2. Improve path handling

Current UX will be fragile unless paths are normalized consistently.

Add client helpers for:

- `ftp:/absolute/path`
- absolute virtual paths without prefix
- relative paths resolved against current FTP cwd
- local path vs ftp path disambiguation

### 3. Add outbound DCC bridge from VFS

When the source path is `ftp:/...`:

1. Resolve metadata and size through the VFS path.
2. Pull bytes from the existing PRET/VFS download channel.
3. Serve those bytes through a normal DCC SEND socket to the peer.
4. Preserve standard DCC filename and size behavior.

This is a bridge:

- VFS/FTPD on the source side
- DCC on the IRC side

The client should stream rather than buffering whole files into memory.

### 4. Add inbound DCC receive to VFS upload

When accepting a DCC file send:

1. Receive the stream from the IRC peer using the client’s DCC receive path.
2. Push bytes directly into the existing VFS upload path.
3. Allow target selection in the FTP namespace.
4. Emit progress and completion notices.

Recommended first implementation:

- receive to a stream and upload immediately
- avoid a temporary local file unless the current DCC implementation makes direct streaming too invasive

Fallback if needed:

- stage to a temp local file and then upload through the VFS channel

Direct stream is preferred, but not mandatory for phase 1.

### 5. Keep mIRC compatibility

The DCC offer generated by `csc-client` should remain standard enough for mIRC and similar clients.

Validate:

- quoted vs unquoted filename handling
- IP/port encoding
- size field correctness
- resume/ack behavior if supported

## Protocol and UX Details

### FTP path prefix

Use `ftp:/path/to/file` as the explicit FTP namespace marker.

Reason:

- avoids ambiguity with local filesystem paths
- makes `/dcc send nick ftp:/...` unambiguous

### Current working directory

Keep a separate FTP cwd client-side.

Example:

- `/ftp cwd /pub/releases`
- `/ftp ls`
- `/ftp get app.zip`
- `/ftp upload build.zip .`

Client resolves relative entries against the FTP cwd before invoking the transport.

### Error handling

Every failure should return an IRC-friendly notice:

- permission denied
- path not found
- invalid target
- rename state missing
- DCC peer rejected
- upload interrupted
- download interrupted

### Safety limits

Add guardrails:

- deny path traversal outside the virtual root
- require explicit overwrite behavior
- configurable file size limits for DCC bridging if necessary
- timeout stale rename state

## Suggested Implementation Phases

### Phase 1: IRCop FTP UX over existing VFS

Deliver:

- `/ftp cwd`
- `/ftp pwd`
- `/ftp ls`
- `/ftp get`
- `/ftp upload`
- `/ftp rnfr`
- `/ftp rnto`
- `/ftp mv`
- `/ftp del`
- oper-only gate
- logging/audit trail

This phase already replaces most standalone FTP client usage.

### Phase 2: DCC send from FTP namespace

Deliver:

- `/dcc send nick ftp:/path/to/file.ext`
- VFS-to-DCC streaming bridge
- progress/error notices

### Phase 3: DCC receive into FTP namespace

Deliver:

- receive normal DCC SEND in `csc-client`
- accept into FTP destination
- upload into VFS/FTPD
- inbox/default-path behavior

### Phase 4: Optional parity and polish

Possible additions:

- `/ftp mkdir`
- `/ftp stat`
- `/ftp put` alias
- tab completion/help text
- resume support for DCC
- configurable auto-accept rules for trusted senders

## Testing Plan

### Unit/integration coverage

Server:

- oper-only authorization
- path normalization and root confinement
- rename flow state
- sync trigger on upload/delete/rename

Client:

- `/ftp` command parsing
- cwd-relative path resolution
- `ftp:` path detection
- upload/download path routing

DCC bridge:

- VFS file streamed as DCC SEND
- inbound DCC stream routed to VFS upload
- large file streaming without full-memory buffering

### Manual verification

Environment:

- `haven.4346` local
- `haven.ef6e` hub if cross-server routing matters for DCC notices
- at least one `csc-client`
- one standard IRC client such as mIRC

Manual scenarios:

1. IRCop runs `/ftp cwd /`
2. IRCop runs `/ftp ls`
3. IRCop downloads a known file with `/ftp get`
4. IRCop uploads a file with `/ftp upload`
5. IRCop renames it with `/ftp rnfr` and `/ftp rnto`
6. IRCop deletes a test file
7. IRCop runs `/dcc send nick ftp:/path/to/file`
8. mIRC receives the DCC file successfully
9. mIRC sends a file to `csc-client`
10. `csc-client` accepts and uploads it into the FTP namespace

## Risks

- Existing VFS behavior may already be used by non-opers, so tightening access could be disruptive
- DCC implementation may be incomplete in `csc-client`, making the receive path larger than the send path
- PRET/VFS transfer code may not expose enough metadata for a clean streaming bridge
- Cross-platform socket behavior may need platform-layer cleanup if DCC handling is currently ad hoc

## Recommended First Cut

If implementation starts immediately, the lowest-risk order is:

1. Make `/ftp` a client alias over existing `VFS`
2. Enforce IRCop-only on the server handler
3. Verify upload/download/rename/delete entirely over IRC without DCC
4. Add VFS-backed outbound DCC send
5. Add inbound DCC receive into VFS

This gets useful operator value early and keeps the DCC work isolated to a later phase instead of blocking the entire feature.

## Acceptance Criteria

The work is done when all of the following are true:

- IRCops can browse and manage the FTP virtual filesystem entirely from IRC
- No standalone FTP client is required for normal file management
- `/dcc send nick ftp:/path/to/file.ext` works from `csc-client`
- A DCC file sent from a normal IRC client can be accepted by `csc-client` and written into the FTP virtual filesystem
- All filesystem mutations still flow through the existing FTPD/VFS/sync architecture
- Access is restricted to IRCops
- Actions are logged and test-covered
