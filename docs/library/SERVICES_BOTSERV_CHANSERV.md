# IRC Services Documentation: BotServ and ChanServ

## Overview

CSC implements two IRC service modules to provide persistent channel management and bot registration capabilities:

- **ChanServ** - Channel registration and access control service
- **BotServ** - Channel bot registration and management service

Both services operate as virtual IRC users that clients can message with commands. They integrate with the server's persistent storage system to maintain state across server restarts.

---

## ChanServ - Channel Registration Service

### Purpose

ChanServ allows users to register channels and configure persistent access controls, topics, and ban lists. Registered channels automatically apply their saved state (operator/voice status, topic, bans) when users join.

### Architecture

**Service File**: `/opt/csc/packages/csc_shared/services/chanserv_service.py`
**Storage File**: `chanserv.json` (managed by `PersistentStorageManager`)
**Integration**: `/opt/csc/packages/csc_server/server_message_handler.py`

The ChanServ service provides:
- Channel ownership and registration tracking
- Persistent operator and voice access lists
- Persistent ban lists and enforcement
- Topic protection and persistence
- Mode enforcement with NickServ integration

### Command Reference

All ChanServ commands are sent via PRIVMSG to the virtual user `ChanServ`:

```irc
/msg ChanServ <COMMAND> [arguments...]
```

#### REGISTER <#channel> <topic>
Register a channel under your ownership.

**Requirements**:
- You must be a channel operator (`+o`) in the channel
- Channel must not already be registered
- You must be identified with NickServ (if enforcement enabled)

**Example**:
```irc
/msg ChanServ REGISTER #mychannel Welcome to my channel
```

**Server Response**:
```
:ChanServ!ChanServ@csc.server NOTICE YourNick :Channel #mychannel registered successfully.
```

**Persistence**: Creates channel entry in `chanserv.json` with:
```json
{
  "channel": "#mychannel",
  "owner": "YourNick",
  "topic": "Welcome to my channel",
  "oplist": [],
  "voicelist": [],
  "banlist": [],
  "enforce_topic": false,
  "enforce_mode": false,
  "enforce_ban": false,
  "strict_op": false,
  "strict_voice": false,
  "created_at": 1234567890.0
}
```

#### OP <#channel> <nick>
Add a user to the channel's persistent operator list.

**Requirements**:
- You must be the channel owner or an IRC operator
- Channel must be registered
- Target user will receive `+o` mode when they join

**Example**:
```irc
/msg ChanServ OP #mychannel TrustedUser
```

**Effect**: Adds `TrustedUser` to the `oplist` array. When `TrustedUser` joins `#mychannel`, they automatically receive operator status.

#### DEOP <#channel> <nick>
Remove a user from the channel's persistent operator list.

**Requirements**:
- You must be the channel owner or an IRC operator
- Channel must be registered

**Example**:
```irc
/msg ChanServ DEOP #mychannel FormerOp
```

**Effect**: Removes the user from `oplist`. If currently in channel, their `+o` mode is removed immediately.

#### VOICE <#channel> <nick>
Add a user to the channel's persistent voice list.

**Requirements**:
- You must be the channel owner or an IRC operator
- Channel must be registered
- Target user will receive `+v` mode when they join

**Example**:
```irc
/msg ChanServ VOICE #mychannel ContributorNick
```

**Effect**: Adds to `voicelist` array and grants `+v` mode.

#### DEVOICE <#channel> <nick>
Remove a user from the channel's persistent voice list.

**Example**:
```irc
/msg ChanServ DEVOICE #mychannel ContributorNick
```

**Effect**: Removes from `voicelist`. If in channel, removes `+v` mode immediately.

#### BAN <#channel> <mask>
Add a ban mask to the channel's persistent ban list.

**Requirements**:
- You must be the channel owner or an IRC operator
- Channel must be registered

**Mask Format**: Standard IRC ban masks (e.g., `*!*@badhost.com`, `BadUser!*@*`)

**Example**:
```irc
/msg ChanServ BAN #mychannel *!*@spam.example.com
```

**Effect**:
- Adds mask to `banlist` array
- Kicks any currently connected users matching the mask
- Prevents future joins from users matching the mask

#### UNBAN <#channel> <mask>
Remove a ban mask from the channel's persistent ban list.

**Example**:
```irc
/msg ChanServ UNBAN #mychannel *!*@spam.example.com
```

**Effect**: Removes the mask from `banlist`. Users matching this mask can now join.

#### INFO <#channel>
Display registration information for a channel.

**Example**:
```irc
/msg ChanServ INFO #mychannel
```

**Response**:
```
:ChanServ!ChanServ@csc.server NOTICE YourNick :Channel: #mychannel
:ChanServ!ChanServ@csc.server NOTICE YourNick :Owner: ChannelOwner
:ChanServ!ChanServ@csc.server NOTICE YourNick :Topic: Welcome to my channel
:ChanServ!ChanServ@csc.server NOTICE YourNick :Oplists: 3, Voicelist: 2, Banlist: 1
:ChanServ!ChanServ@csc.server NOTICE YourNick :Registered: 2025-01-15 14:30:00
```

#### LIST
List all registered channels.

**Example**:
```irc
/msg ChanServ LIST
```

**Response**:
```
:ChanServ!ChanServ@csc.server NOTICE YourNick :Registered channels:
:ChanServ!ChanServ@csc.server NOTICE YourNick :  #mychannel (Owner: ChannelOwner)
:ChanServ!ChanServ@csc.server NOTICE YourNick :  #otherchan (Owner: AnotherUser)
```

### Enforcement Modes

ChanServ supports several enforcement flags (stored in channel registration):

#### Topic Enforcement (`enforce_topic`)
When enabled, only the channel owner can change the topic.

**Setting**: Modified via MODE command with `+T` flag
```irc
/msg ChanServ MODE #mychannel +T
```

**Behavior**: Non-owner `/TOPIC` commands are rejected with:
```
:csc.server 482 YourNick #mychannel :Only the channel owner can change the topic (+T)
```

#### Mode Enforcement (`enforce_mode`)
When enabled, only identified users (via NickServ) can receive op/voice modes from ChanServ.

**Setting**: Modified via MODE command with `+E` flag
```irc
/msg ChanServ MODE #mychannel +E
```

**Behavior**: Users on `oplist`/`voicelist` who are not identified with NickServ will not automatically receive their modes on join.

#### Strict Op Mode (`strict_op`)
When enabled with `+O`, only users on the `oplist` can receive operator status.

#### Strict Voice Mode (`strict_voice`)
When enabled with `+V`, only users on the `voicelist` can receive voice status.

### Join-Time State Application

When a user joins a registered channel, ChanServ automatically applies:

1. **Topic**: Set from registered topic if channel topic is empty
2. **Ban Check**: Deny join if user matches any mask in `banlist`
3. **Auto-Op**: Grant `+o` if user's nick is in `oplist` (requires identification if `enforce_mode` is on)
4. **Auto-Voice**: Grant `+v` if user's nick is in `voicelist` (requires identification if `enforce_mode` is on)

This is implemented in the `handle_join()` method of `server_message_handler.py`:

```python
# ChanServ Enforcement (JOIN)
chanserv_info = self.server.storage.chanserv_get(chan_name)
if chanserv_info:
    # Check banlist
    banlist = chanserv_info.get("banlist", [])
    for mask in banlist:
        if self._match_ban_mask(mask, nick_user_host):
            # Deny join
            return

    # Auto-op/voice
    is_identified = self.server.nickserv_identified.get(addr) == nick
    if nick.lower() in [n.lower() for n in chanserv_info.get("oplist", [])]:
        initial_modes.add("o")
    elif nick.lower() in [n.lower() for n in chanserv_info.get("voicelist", [])]:
        initial_modes.add("v")
```

### Data Storage

**File**: `chanserv.json` (in server working directory)

**Schema**:
```json
{
  "version": 1,
  "channels": {
    "#channelname": {
      "channel": "#channelname",
      "owner": "OwnerNick",
      "topic": "Channel topic text",
      "oplist": ["nick1", "nick2"],
      "voicelist": ["nick3", "nick4"],
      "banlist": ["*!*@badhost.com"],
      "enforce_topic": false,
      "enforce_mode": false,
      "enforce_ban": false,
      "strict_op": false,
      "strict_voice": false,
      "created_at": 1234567890.0
    }
  }
}
```

**Storage Operations**:
- `chanserv_register(channel, owner, topic)` - Create new registration
- `chanserv_get(channel)` - Retrieve channel info (returns `None` if not registered)
- `chanserv_update(channel, info)` - Update registration info
- `chanserv_drop(channel)` - Unregister channel

**Atomic Writes**: All writes use `PersistentStorageManager._atomic_write()` to guarantee data integrity:
1. Write to temporary file
2. fsync() to disk
3. Atomic rename over existing file

### API Integration

ChanServ integrates with the server through several entry points:

#### Message Handler
In `server_message_handler.py`, the `_handle_chanserv()` method routes PRIVMSG commands:

```python
def _handle_chanserv(self, msg, addr):
    """Handle PRIVMSG ChanServ :COMMAND args"""
    text = msg.params[-1].strip()
    parts = text.split()
    subcmd = parts[0].upper()

    if subcmd == "REGISTER":
        self._chanserv_register(parts[1:], addr)
    elif subcmd == "OP":
        self._chanserv_op(parts[1:], addr)
    # ... etc
```

#### JOIN Handler
The `handle_join()` method checks ChanServ registration and applies state:

```python
chanserv_info = self.server.storage.chanserv_get(chan_name)
if chanserv_info:
    # Apply banlist, auto-op, auto-voice, topic
```

#### MODE Handler
The `handle_mode()` method enforces ChanServ mode restrictions:

```python
if chanserv_info and chanserv_info.get("enforce_mode"):
    # Check NickServ identification before granting modes
```

#### TOPIC Handler
The `handle_topic()` method enforces topic protection:

```python
if chanserv_info and chanserv_info.get("enforce_topic"):
    # Only allow owner to change topic
```

---

## BotServ - Bot Registration Service

### Purpose

BotServ allows channel owners to register automated bots for their channels. Bots are associated with a channel and stored with authentication credentials for later automation features (log monitoring, auto-responses, etc.).

### Architecture

**Service File**: `/opt/csc/packages/csc_shared/services/botserv_service.py`
**Storage File**: `botserv.json` (managed by `PersistentStorageManager`)
**Integration**: `/opt/csc/packages/csc_server/server_message_handler.py`

BotServ provides:
- Bot registration tied to specific channels
- Channel ownership validation (via ChanServ)
- Password-protected bot credentials
- Bot listing and management

### Command Reference

All BotServ commands are sent via PRIVMSG to the virtual user `BotServ`:

```irc
/msg BotServ <COMMAND> [arguments...]
```

#### ADD <botnick> <#channel> <password>
Register a bot for a channel.

**Requirements**:
- Channel must be registered with ChanServ first
- You must be the channel owner (or an IRC operator)
- Bot nickname must be unique for this channel

**Example**:
```irc
/msg BotServ ADD LogBot #mychannel secretpass123
```

**Server Response**:
```
:BotServ!BotServ@csc.server NOTICE YourNick :Bot LogBot registered for #mychannel
```

**Persistence**: Creates entry in `botserv.json`:
```json
{
  "botnick": "LogBot",
  "channel": "#mychannel",
  "owner": "YourNick",
  "password": "secretpass123",
  "registered_at": 1234567890.0,
  "logs": [],
  "logs_enabled": false
}
```

**Use Cases**:
- Register automated log bots for channel monitoring
- Set up response bots for channel automation
- Create service bots for channel management

#### DEL <botnick> <#channel>
Unregister a bot from a channel.

**Requirements**:
- You must be the channel owner or an IRC operator
- Bot must be registered for the specified channel

**Example**:
```irc
/msg BotServ DEL LogBot #mychannel
```

**Server Response**:
```
:BotServ!BotServ@csc.server NOTICE YourNick :Bot LogBot removed from #mychannel
```

**Effect**: Deletes the bot entry from `botserv.json`.

#### LIST [#channel]
List registered bots. If channel is specified, shows only bots for that channel.

**Examples**:
```irc
# List all bots
/msg BotServ LIST

# List bots for specific channel
/msg BotServ LIST #mychannel
```

**Server Response**:
```
:BotServ!BotServ@csc.server NOTICE YourNick :Registered bots:
:BotServ!BotServ@csc.server NOTICE YourNick :  LogBot on #mychannel (Owner: YourNick)
:BotServ!BotServ@csc.server NOTICE YourNick :  WelcomeBot on #otherchan (Owner: AnotherUser)
```

### Channel Integration

BotServ requires channels to be registered with ChanServ before bots can be added. This ensures:

1. **Ownership Validation**: Only channel owners can register bots
2. **Channel Persistence**: Bots persist across server restarts
3. **Access Control**: Bot management is tied to ChanServ ownership

**Workflow**:
```irc
# Step 1: Register channel with ChanServ
/msg ChanServ REGISTER #mychannel Welcome message

# Step 2: Register bot with BotServ
/msg BotServ ADD MyBot #mychannel botpassword

# Step 3: Bot can now be used for automation
```

**Validation Check** (from `server_message_handler.py`):
```python
def _botserv_add(self, args, addr):
    # Check ChanServ registration
    chanserv_info = self.server.storage.chanserv_get(chan_name)
    if not chanserv_info:
        self._botserv_notice(addr, f"Channel {chan_name} is not registered with ChanServ.")
        return

    # Verify ownership
    if chanserv_info["owner"].lower() != nick.lower() and nick.lower() not in self.server.opers:
        self._botserv_notice(addr, f"Permission denied. You are not the owner of {chan_name}.")
        return
```

### Data Storage

**File**: `botserv.json` (in server working directory)

**Schema**:
```json
{
  "version": 1,
  "bots": {
    "#channel:botnick": {
      "botnick": "LogBot",
      "channel": "#channel",
      "owner": "OwnerNick",
      "password": "encrypted_or_plain",
      "registered_at": 1234567890.0,
      "logs": [],
      "logs_enabled": false
    }
  }
}
```

**Key Format**: Bots are indexed by `"{channel}:{botnick}"` (lowercase) to ensure uniqueness per channel.

**Storage Operations**:
- `botserv_register(channel, botnick, owner, password)` - Create new bot
- `botserv_get(channel, botnick)` - Retrieve specific bot info
- `botserv_get_for_channel(channel)` - Get all bots for a channel
- `botserv_drop(channel, botnick)` - Unregister bot

**Atomic Writes**: Uses same `PersistentStorageManager` atomic write pattern as ChanServ.

### Future Extensions

The BotServ implementation includes fields for future automation features:

**Log Monitoring** (`logs`, `logs_enabled`):
- Field: `logs` array stores bot activity logs
- Field: `logs_enabled` boolean controls whether logging is active
- Purpose: Support automated log echoing and monitoring (see Task 100)

**Potential Features**:
- Auto-response triggers
- Channel statistics tracking
- Automated moderation actions
- Integration with external bot frameworks

### API Integration

BotServ integrates with the server through the message handler:

#### Message Handler
In `server_message_handler.py`, the `_handle_botserv()` method routes commands:

```python
def _handle_botserv(self, msg, addr):
    """Handle PRIVMSG BotServ :COMMAND args"""
    text = msg.params[-1].strip()
    parts = text.split()
    subcmd = parts[0].upper()

    if subcmd == "ADD":
        self._botserv_add(parts[1:], addr)
    elif subcmd == "DEL":
        self._botserv_del(parts[1:], addr)
    elif subcmd == "LIST":
        self._botserv_list(parts[1:], addr)
```

#### Storage Integration
Accessed via `server.storage.botserv_*()` methods:

```python
# Register bot
success = self.server.storage.botserv_register(
    channel=chan_name,
    botnick=botnick,
    owner=nick,
    password=password
)

# Retrieve bot
bot_info = self.server.storage.botserv_get(chan_name, botnick)

# List bots
bots = self.server.storage.botserv_get_for_channel(chan_name)
```

---

## Usage Examples

### Scenario 1: Setting Up a Registered Channel

```irc
# As user "ChannelOwner"
JOIN #support
MODE #support +o ChannelOwner

# Register the channel
/msg ChanServ REGISTER #support Welcome to our support channel

# Add trusted operators
/msg ChanServ OP #support TrustedHelper
/msg ChanServ OP #support AnotherAdmin

# Add contributors to voice list
/msg ChanServ VOICE #support RegularContributor

# Ban a problematic user
/msg ChanServ BAN #support *!*@spammer.example.com

# Enable topic protection
/msg ChanServ MODE #support +T
```

**Result**: Channel `#support` is now registered with persistent ops, voice, and bans. Topic can only be changed by ChannelOwner.

### Scenario 2: Registering a Log Bot

```irc
# As channel owner
/msg ChanServ REGISTER #logs Channel activity logs

# Add log bot
/msg BotServ ADD ActivityLogger #logs logpass123

# Verify registration
/msg BotServ LIST #logs
```

**Response**:
```
:BotServ!BotServ@csc.server NOTICE ChannelOwner :Registered bots:
:BotServ!BotServ@csc.server NOTICE ChannelOwner :  ActivityLogger on #logs (Owner: ChannelOwner)
```

### Scenario 3: Auto-Op on Join

```irc
# As channel owner
/msg ChanServ OP #mychannel TrustedUser

# Later, TrustedUser joins
JOIN #mychannel
```

**Server automatically sends**:
```
:ChanServ!ChanServ@csc.server MODE #mychannel +o TrustedUser
```

**Result**: `TrustedUser` receives operator status immediately upon joining, without manual intervention.

### Scenario 4: Ban Enforcement

```irc
# As channel owner
/msg ChanServ BAN #private *!baduser@*

# When baduser tries to join
JOIN #private
```

**Server rejects join**:
```
:csc.server 474 baduser #private :Cannot join channel (ChanServ BAN) - You are banned
```

---

## Implementation Notes

### Service Architecture

Both services follow the CSC service module pattern:

1. **Service Class**: Inherits from `Service` base class
2. **Command Methods**: Each IRC command maps to a method (e.g., `add()`, `register()`)
3. **Message Handler Integration**: Commands routed through `_handle_chanserv()` and `_handle_botserv()`
4. **Storage Layer**: All persistence via `PersistentStorageManager`

### Virtual IRC Users

ChanServ and BotServ appear as IRC users with the hostmask:
- `ChanServ!ChanServ@csc.server`
- `BotServ!BotServ@csc.server`

They send NOTICE messages to users and MODE/TOPIC messages to channels.

### Case Insensitivity

All channel and nickname comparisons are case-insensitive:
- Storage keys use `.lower()` normalization
- Comparison logic uses `nick.lower()` for matching
- Original case is preserved in display fields

### Operator Override

IRC operators (opers) can perform owner-only actions on any registered channel:
```python
if chanserv_info["owner"].lower() != nick.lower() and nick.lower() not in self.server.opers:
    # Permission denied
```

This allows server administrators to manage any channel.

### Atomic Storage

All state changes use atomic file operations:
1. Write new data to `.tmp` file
2. Call `os.fsync()` to flush to disk
3. Atomically rename `.tmp` over existing file

This guarantees no partial writes or corruption on power failure.

### Server Restart Behavior

On server restart:
1. `PersistentStorageManager` loads `chanserv.json` and `botserv.json`
2. Channel state is restored via `apply_recovery_state()`
3. Registered channels receive their topics, bans, and settings
4. When users join, auto-op/voice is applied based on stored lists

**Recovery Code** (from `storage.py`):
```python
def apply_recovery_state(self, channel_manager):
    # Apply ChanServ registration state
    chanserv_data = self.load_chanserv()
    chanserv_channels = chanserv_data.get("channels", {})
    for name, info in chanserv_channels.items():
        if key in channel_manager.channels:
            channel = channel_manager.channels[key]
            channel.topic = info.get("topic", "")
            # Apply bans, modes, etc.
```

### NickServ Integration

ChanServ integrates with NickServ for identity verification:

- `enforce_mode` flag requires users to be identified with NickServ before receiving auto-op/voice
- Identification state tracked in `server.nickserv_identified` dict
- Check performed during JOIN: `is_identified = self.server.nickserv_identified.get(addr) == nick`

---

## Service Lifecycle

### Initialization

Services are instantiated by the `Service` class loader on first command:

```python
# In service.py
module_name = f"services.{class_name.lower()}_service"
module = importlib.import_module(module_name)
instance = module_class(self)  # Pass Service instance
self.loaded_modules[class_name_raw] = instance
```

Each service receives a reference to the `Service` instance, which provides access to:
- `self.server` - Main server instance
- `self.server.storage` - Storage manager
- `self.log()` - Logging method

### Command Routing

Commands flow through the service layer:

1. Client sends: `PRIVMSG ChanServ :REGISTER #chan topic`
2. `server_message_handler.py` intercepts PRIVMSG to ChanServ/BotServ
3. Handler calls `_handle_chanserv()` or `_handle_botserv()`
4. Handler method parses command and arguments
5. Handler calls storage operations and sends responses

**No direct service method invocation**: The service classes in `services/` provide structure but commands are handled directly by `server_message_handler.py` for performance.

### Error Handling

Services validate inputs and send user-friendly error notices:

```python
if len(args) < 2:
    self._chanserv_notice(addr, "Syntax: REGISTER <#chan> <topic>")
    return

if not chanserv_info:
    self._chanserv_notice(addr, f"Channel {chan_name} is not registered.")
    return
```

Errors are sent as NOTICE messages from the service user (ChanServ/BotServ).

---

## Testing

Both services have comprehensive test coverage:

- **ChanServ Tests**: `/opt/csc/tests/test_chanserv.py`
- **BotServ Tests**: `/opt/csc/tests/test_botserv.py`
- **BotServ Log Tests**: `/opt/csc/tests/test_botserv_logs.py`

Tests verify:
- Registration and ownership validation
- Op/voice/ban list persistence
- ChanServ enforcement modes
- BotServ channel requirement
- Atomic storage operations
- Join-time state application
- Error handling and permission checks

**Run tests** (via automated cron system):
```bash
# Tests run automatically on cron schedule
# Check test results:
cat tests/logs/test_chanserv.log
cat tests/logs/test_botserv.log
```

---

## Summary

**ChanServ** provides persistent channel management with:
- Channel registration and ownership
- Automatic operator/voice granting on join
- Persistent ban enforcement
- Topic protection
- NickServ integration for identity verification

**BotServ** provides bot registration with:
- Channel-specific bot credentials
- ChanServ integration for ownership validation
- Foundation for future automation features

Both services use atomic JSON storage for reliability and integrate seamlessly with the IRC server's message handling and channel management systems.
