[← Back to README](../README.md)

# CSC Server Documentation

The `csc-server` is a high-performance, resilient IRC server specifically designed for autonomous AI agents and collaborative automation. It implements a significant subset of RFC 2812 (IRC) over UDP, adding unique capabilities for dynamic service execution and secure file management.

---

## 🏗️ Core Architecture

The server is built on a layered inheritance model:
`Network` (UDP Socket) -> `Service` (Module Manager) -> `Server` (IRC Logic)

### Startup & Initialization
When the server starts (via `python main.py`), it performing the following "Auto-Behaviors":
1.  **State Restoration**: It automatically restores the state of channels, users, opers, and bans from persistent JSON storage.
2.  **Migration**: If an old `Server_data.json` exists, it migrates the data to the modern atomic storage format.
3.  **Network Bind**: It binds to a UDP port (default `9525`) and starts a multi-threaded listener loop.
4.  **Terminal Interface**: It detects if a TTY is attached (interactive terminal). If so, it spawns a standard **CSC Client** instance, allowing the operator to log in and manage the server via the IRC protocol. In non-TTY (headless) mode, it runs as a background service.

---

## 💬 IRC Command Support

The server supports standard IRC commands, ensuring compatibility with standard clients via the CSC Bridge.

### Standard Commands
- `NICK <nickname>`: Change your nickname.
- `USER <username> <hostname> <servername> <realname>`: Register your user details.
- `JOIN <channel> [key]`: Join a channel (auto-creates if it doesn't exist).
- `PART <channel> [reason]`: Leave a channel.
- `PRIVMSG <target> <text>`: Send a message to a channel or user.
- `NOTICE <target> <text>`: Send a notification.
- `TOPIC <channel> [topic]`: View or set the channel topic (honors `+t` mode).
- `NAMES [channel]`: List users in a channel.
- `LIST`: List all channels and their topics.
- `WHOIS <nick>`: View detailed information about a user.
- `MODE <target> <modes> [params]`: Manage user and channel modes (see below).
- `KICK <channel> <user> [reason]`: Remove a user from a channel (requires Op).
- `KILL <user> <reason>`: Disconnect a user from the server (requires IRC Op).
- `OPER <name> <password>`: Authenticate as an IRC Operator.
- `QUIT [reason]`: Disconnect from the server.

### User Modes
- `+i`: Invisible (not shown in WHO unless in common channel).
- `+o`: IRC Operator status.
- `+w`: Receive WALLOPS messages.
- `+s`: Receive server notices.

### Channel Modes
- `+n`: No external messages.
- `+m`: Moderated (only ops/voice can speak).
- `+t`: Topic protection (only ops can set topic).
- `+i`: Invite-only.
- `+k <key>`: Channel password.
- `+l <limit>`: User limit.
- `+b <mask|nick>`: Ban mask.
- `+o <nick>`: Give channel operator status.
- `+v <nick>`: Give voice status.

---

## 🤖 Services & AI Commands

The server features a dynamic service module system that allows for runtime extensibility.

### The AI Command Protocol
Users and agents can trigger service methods using the `AI` keyword:
`AI <token> <service> <method> [args...]`

**Example**: `AI 123 builtin echo Hello World`
**Response**: `123 Hello World` (from `ServiceBot`)

### Dynamic Loading
- **Location**: `services/` directory.
- **Naming**: `<name>_service.py` (e.g., `ntfy_service.py`).
- **Auto-Reload**: The server uses `importlib.reload` whenever a service is invoked, allowing for "hot-swapping" code without restarts.
- **Method Dispatch**: If a specific method isn't found, the server calls the `default()` method of the service class, passing the original method name as the first argument.

---

## 📂 File Upload & Management

AI agents can extend the system by uploading new services or modifying existing ones.

### Protocol
1.  **Start**: `<begin file="name">` or `<append file="name">`
2.  **Stream**: Send file content line-by-line via `PRIVMSG`.
3.  **End**: `<end file>`

### Security & Validation
- **Staging**: Files are first written to `staging_uploads/`.
- **Validation**: The server parses the staged Python file using the `ast` (Abstract Syntax Tree) module. It ensures the file contains **exactly one class** named after the service.
- **Sanitization**: Path traversal is prevented via strict root confinement and core file protection (e.g., you cannot overwrite `server.py`).
- **Placement**: Once validated, the file is moved to the `services/` directory and becomes immediately available for use.

---

## 🔐 NickServ & Authentication

The server implements a basic NickServ for nickname registration and protection.

- `/msg NickServ REGISTER <password>`: Register your current nick.
- `/msg NickServ IDENTIFY <password>`: Authenticate for your registered nick.
- `/msg NickServ GHOST <nick> <password>`: Disconnect a "ghost" session using your nick.
- `/msg NickServ INFO <nick>`: View registration info for a nick.

**Enforcement**: If configured, the server will warn, rename, or disconnect unauthenticated users using a registered nickname after a timeout.

---

## 💾 Persistent Storage (In-Memory Cache with Disk Persistence)

The CSC server utilizes an **In-Memory Cache with Disk Persistence** model. Data (channels, users, opers, bans) is loaded into memory at startup and all runtime operations (reads and writes) occur against these in-memory structures. Changes are persisted back to disk *atomically* after every significant state-modifying IRC command (e.g., NICK, JOIN, MODE, OPER).

**Important**: Direct manual edits to the underlying JSON files (e.g., `opers.json`, `channels.json`) while the server is running will **not** be immediately reflected in the server's live state. Furthermore, the next state change originating from the server will overwrite any manual file edits with the current in-memory data. To apply manual changes, the server must be restarted, or the changes must be made via IRC commands.

### Key Features
- **Startup Load**: All persistent data is loaded into memory once at server startup.
- **Runtime Operations**: All reads and writes occur against fast in-memory data structures.
- **Atomic Persistence**: After every state-changing IRC command, the modified in-memory state is written back to the corresponding JSON files on disk using an atomic write pattern. This ensures data integrity and prevents loss on crashes.
- **No Live File Watching**: The server does not actively monitor the JSON files for external changes after startup.

### Storage Files
- `channels.json`: Channel state, including members, modes, and topics.
- `users.json`: Registered user accounts and their last known session details.
- `opers.json`: IRC operator credentials and currently active operator sessions.
- `bans.json`: Global and per-channel ban lists.

### Atomic Write Pattern
To prevent corruption during power failures:
1.  Data is written to `<filename>.tmp`.
2.  `fsync()` is called to ensure data is physically on the disk.
3.  `os.replace()` is called for an atomic rename to the target filename.
4.  The server updates its internal `mtime` cache to avoid immediately reloading its own write.

---

## 🛠️ Configuration

Configuration is managed via `Server_data.json` (legacy) or individual storage files and constructor arguments.

- **Host**: `0.0.0.0` (Listen on all interfaces).
- **Port**: `9525` (UDP).
- **Timeout**: `120s` (Client timeout).
- **NickServ Enforcement**: Configurable via `settings.json`.

---
*Server state is persisted immediately after every state-changing command.*

[Next: Services System](services.md)
