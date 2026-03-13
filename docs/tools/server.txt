SERVER SUBMODULE MAP
==================================================

── irc/packages/csc-service/csc_service/server/__init__.py ──

── irc/packages/csc-service/csc_service/server/channel.py ──
# Channel and ChannelManager for IRC-style channel support.
  class Channel:  # Represents a single IRC channel.
    def __init__(self, name: str)  # Initializes the instance.
    def add_member(self, nick: str, addr: tuple, modes: Optional[Set[str]]=None)  # Add a member to the channel.
    def remove_member(self, nick: str)  # Remove a member from the channel.
    def has_member(self, nick: str) -> bool  # Check if nick is in this channel.
    def get_names_list(self) -> str  # Return space-separated names list with @/+ prefix for ops/voiced.
    def member_count(self) -> int  # Returns the number of members in the channel.
    def is_op(self, nick: str) -> bool  # Check if nick has channel operator mode.
    def has_voice(self, nick: str) -> bool  # Check if nick has voice (+v) mode.
    def can_speak(self, nick: str) -> bool  # Check if nick can send messages to this channel.
    def can_set_topic(self, nick: str) -> bool  # Check if nick can set the channel topic.
  class ChannelManager:  # Manages all channels on the server.
    def __init__(self)  # Initializes the instance.
    def ensure_channel(self, name: str) -> Channel  # Create channel if it doesn't exist, return it.
    def get_channel(self, name: str) -> Optional[Channel]  # Get channel by name, or None.
    def remove_channel(self, name: str) -> bool  # Remove a channel. Cannot remove the default channel.
    def list_channels(self) -> List[Channel]  # Return all channels.
    def find_channels_for_nick(self, nick: str) -> List[Channel]  # Find all channels a nick is a member of.
    def remove_nick_from_all(self, nick: str) -> List[str]  # Remove a nick from all channels. Returns list of channel names they were in.

── irc/packages/csc-service/csc_service/server/client.py ──
  class Client(Network):  # UDP client with IRC protocol support, identity, macros, aliases, and text-file uploads.
    def __init__(self, config_path=None)  # Initializes the instance.
    def _load_config(self)  # Loads client configuration from JSON, creating defaults as needed.
    def _save_config(self)  # Saves all client data back to config file.
    def command_server(self, args: str)  # /server <ip> [port]
    def identify(self)  # Send IRC registration sequence: NICK + USER.
    def run(self)  # Starts listener thread and handles input.
    def _input_loop(self)  # Handles blocking user input in a separate thread.
    def _handle_server_message_data(self, msg_data)  # Decodes and routes a message received from the server.
    def _handle_irc_line(self, line)  # Parse and handle a single IRC line from the server.
    def _handle_numeric(self, parsed)  # Handle IRC numeric replies.
    def _handle_privmsg_recv(self, parsed)  # Handle received PRIVMSG.
    def _handle_notice_recv(self, parsed)  # Handle received NOTICE.
    def handle_server_message(self, msg: str)  # Legacy handler — prints messages received from the server.
    def process_command(self, cmd: str)  # Processes user commands with alias/macro expansion.
    def print_local_help(self)  # Displays available client-side commands.
    def send_file(self, filepath: str)  # Sends a text file to the server as PRIVMSG to current channel.

── irc/packages/csc-service/csc_service/server/crypto.py ──
# Diffie-Hellman key exchange and AES-256-GCM encryption for the CSC translator.
  DH_PRIME = int('FFFFFFFFFFFFFFFFC90FDAA22168C234C4C6628B80DC1CD129024E088A67CC74020BBEA6...
  DH_GENERATOR = 2
  class DHExchange:  # Diffie-Hellman key exchange using RFC 3526 Group 14 (2048-bit).
    def __init__(self)  # Generate a new ephemeral DH key pair.
    def compute_shared_key(self, other_public: int) -> bytes  # Derive a 32-byte AES-256 key from the other side's public key.
    def format_init_message(self) -> str  # Format the CRYPTOINIT DH message for initiating key exchange.
    def format_reply_message(self) -> str  # Format the CRYPTOINIT DHREPLY message for completing key exchange.
    def parse_init_message(line: str) -> tuple  # Parse a CRYPTOINIT DH message into its components.
    def parse_reply_message(line: str) -> int  # Parse a CRYPTOINIT DHREPLY message to extract the public key.
  def encrypt(key: bytes, plaintext: bytes) -> bytes  # Encrypt plaintext using AES-256-GCM with a random IV.
  def decrypt(key: bytes, data: bytes) -> bytes  # Decrypt AES-256-GCM data produced by encrypt().
  def is_encrypted(data: bytes) -> bool  # Heuristic to detect whether a datagram contains encrypted or plaintext data.

── irc/packages/csc-service/csc_service/server/data.py ──
  class Data(Log):  # Extends the log class.
    def __init__(self)  # Initializes the Data class.
    def connect(self)  # Connects to a data source file.
    def put_data(self, key: str, value, flush=True)  # Stores a key-value pair and saves the entire data store to file.
    def store_data(self)  # Persists the current data to the storage backend.
    def get_data(self, key: str)  # Retrieves a value from the in-memory data store.
    def init_data(self, source_filename='default')  # Initializes or re-initializes the data object for a subclass instance.
    def run(self)  # Main execution method.

── irc/packages/csc-service/csc_service/server/irc.py ──
# IRC message parser, formatter, and constants for RFC 1459/2812 compliance.
  SERVER_NAME = 'csc-server'
  RPL_WELCOME = '001'
  RPL_YOURHOST = '002'
  RPL_CREATED = '003'
  RPL_MYINFO = '004'
  RPL_LIST = '322'
  RPL_LISTEND = '323'
  RPL_NOTOPIC = '331'
  RPL_TOPIC = '332'
  RPL_NAMREPLY = '353'
  RPL_ENDOFNAMES = '366'
  RPL_MOTDSTART = '375'
  RPL_MOTD = '372'
  RPL_ENDOFMOTD = '376'
  RPL_YOUREOPER = '381'
  ERR_NOSUCHNICK = '401'
  ERR_NOSUCHCHANNEL = '403'
  ERR_CANNOTSENDTOCHAN = '404'
  ERR_NORECIPIENT = '411'
  ERR_NOTEXTTOSEND = '412'
  ERR_NONICKNAMEGIVEN = '431'
  ERR_ERRONEUSNICKNAME = '432'
  ERR_NICKNAMEINUSE = '433'
  ERR_USERNOTINCHANNEL = '441'
  ERR_NOTONCHANNEL = '442'
  ERR_NOTREGISTERED = '451'
  ERR_NEEDMOREPARAMS = '461'
  ERR_ALREADYREGISTRED = '462'
  ERR_PASSWDMISMATCH = '464'
  ERR_CHANOPRIVSNEEDED = '482'
  class IRCMessage:  # Parsed IRC message.
  def parse_irc_message(line: str) -> IRCMessage  # Parse an IRC wire-format line into an IRCMessage.
  def format_irc_message(prefix: Optional[str], command: str, params: Optional[List[str]]=None, trailing: Optional[str]=None) -> str  # Build an IRC wire-format string (without trailing \r\n).
  def numeric_reply(server_name: str, numeric: str, target_nick: str, *text_parts) -> str  # Build a numeric reply line.

── irc/packages/csc-service/csc_service/server/log.py ──
  class Log(Root):  # Extends the root class.
    def __init__(self, server=None)  # Initializes the Log class.
    def log(self, message: str)  # Logs a message to the central project log file and prints to console.
    def help(self)  # Displays base help information for the class.
    def test(self)  # Runs a base self-test for the class.

── irc/packages/csc-service/csc_service/server/main.py ──
  def main()

── irc/packages/csc-service/csc_service/server/network.py ──
  class Network(Platform):
    def __init__(self, host='127.0.0.1', port=9525, name='network')  # Initializes the Network class.
    def _network_listener(self)  # Listens for all incoming data and filters keepalives.
    def start_listener(self)  # Starts the background network listener thread.
    def get_message(self)  # Gets one message tuple (bytes, addr) from the buffer.
    def send(self, message)  # Send a message to the server, encoding if necessary.
    def sock_send(self, data, addr)  # Sends data in chunks, handling both string and bytes types safely.
    def maybe_send_keepalive(self)  # Sends a periodic keep-alive packet silently.
    def close(self)  # Cleanly close the network socket and stop the listener thread.
    def connected_for(self)  # A placeholder method for subclasses to override.

── irc/packages/csc-service/csc_service/server/persistent_clients.bat ──
# @echo off

── irc/packages/csc-service/csc_service/server/root.py ──
  SCRIPT_DIR = dirname(Path(__file__).absolute())
  class Root:  # The first and lowest class in the project's inheritance hierarchy.
    def __init__(self)  # Initializes the Root class.
    def get_command_keyword(self)  # Returns the system command keyword.
    def run(self)  # A placeholder method for subclasses to override.

── irc/packages/csc-service/csc_service/server/secret.py ──
  SCRIPT_DIR = dirname(Path(__file__).absolute())
  def get_gemini_api_key()  # Retrieves the Gemini API key.
  def get_claude_api_key()  # Retrieves the Claude API key.
  def get_known_core_files()  # Returns a list of known core files.
  def load_initial_core_file_context() -> str  # Loads content of key core files to provide initial context to Gemini.
  def get_system_instructions(initial_file_context: str) -> str  # Returns the system instructions.

── irc/packages/csc-service/csc_service/server/server.py ──
  class Server(Service):  # The main UDP server for handling clients, commands, and file operations.
    def __init__(self, host='0.0.0.0', port=9525, timeout=120)  # Initializes the Server.
    def client_registry(self)  # Dynamic property that reads client registry from disk.
    def oper_credentials(self)  # Dynamic property: returns olines dict (v2) for backward compat callers.
    def opers(self)  # Set of lowercase nicks currently holding any oper status.
    def active_opers_info(self)  # Dynamic property: returns {nick_lower: {nick, oper_name, flags, class}}.
    def protect_local_opers(self)  # Whether remote opers without O flag can KILL local opers.
    def _oper_has_flag(self, nick, flag)  # Return True if nick is an active oper with the given flag.
    def oper_has_flag(self, nick, flag)  # Public alias for _oper_has_flag (used by message handler).
    def get_olines(self)  # Return the olines configuration dict.
    def is_local_oper(self, nick)  # Local oper: any oper flag (o, O, a, A).
    def is_global_oper(self, nick)  # Global oper: O flag.
    def is_server_admin(self, nick)  # Server admin: a or A flag.
    def is_net_admin(self, nick)  # Network admin: A flag.
    def wakewords(self)  # Dynamic property that reads wakewords from disk on every access.
    def sync_from_disk(self)  # Reload state from disk ONLY if files have changed.
    def _cleanup_loop(self)  # Periodic background loop to remove timed-out clients.
    def _botserv_log_monitor_loop(self)  # Background loop for BotServ log monitoring and echoing.
    def _syslog_monitor_loop(self)  # Background loop for monitoring syslog and echoing new lines to #syslog.
    def _run_cleanup_once(self)  # Runs the client cleanup logic once.
    def _thread_worker(self, data, addr)  # Worker thread to process each incoming packet.
    def sock_send(self, data, addr)  # Override sock_send to encrypt data if a key is established for addr.
    def _network_loop(self)  # Background loop for processing all incoming network messages.
    def broadcast(self, message, exclude=None)  # Sends a message to all active clients.
    def broadcast_to_channel(self, channel_name, message, exclude=None)  # Send a message to all members of a channel.
    def send_to_nick(self, nick, message)  # Send a message to a specific nick by looking up their address.
    def send_wallops(self, message)  # Send a WALLOPS message to all connected IRC operators.
    def old_broadcast(self, message, exclude=None)  # Sends a message to all active client addresses.
    def sync_persistent_clients(self)  # Writes the in-memory client registry back to persistent storage.
    def _persist_session_data(self)  # Persist current session data to separate JSON files atomically.
    def run(self)  # Starts the server's main network loop and the terminal interface.
    def _wait_for_shutdown(self)  # Block the main thread until SIGTERM/SIGINT is received or SHUTDOWN file exists.
    def get_data(self, key)  # Wrapper for persistent data retrieval.
    def put_data(self, key, value)  # Wrapper for persistent data writes.

── irc/packages/csc-service/csc_service/server/server_file_handler.py ──
  class FileHandler:  # Handles <begin file> … <end file> uploads with full whitespace preservation,
    def __init__(self, server)  # Initializes the FileHandler.
    def start_session(self, addr, line)  # Begins a new upload session from a <begin file="..."> or <append file="..."> tag.
    def abort_session(self, addr)  # Aborts an in-progress upload session, discarding its buffer and logging the event.
    def process_chunk(self, addr, line)  # Buffers a line of text for an active upload session.
    def complete_session(self, addr)  # Completes an upload session, performs final security validation,

── irc/packages/csc-service/csc_service/server/server_message_handler.py ──
# IRC-compliant message handler for csc-server.
  NICK_RE = re.compile('^[A-Za-z\\[\\]\\\\`_^{|}][A-Za-z0-9\\[\\]\\\\`_^{|}\\-]*$')
  class MessageHandler:  # Handles all incoming UDP messages from clients, acting as the central router
    def __init__(self, server, file_handler)  # Initializes the instance.
    def process(self, data, addr)  # Process a raw UDP datagram from a client.
    def _handle_file_session_line(self, addr, line_stripped, raw_line)  # Handle a line while in an active file upload session.
    def _dispatch_irc_command(self, msg, addr, raw_line)  # Route an IRC command to the appropriate handler.
    def _ensure_reg_state(self, addr)  # Ensure registration state exists for addr.
    def _handle_pass(self, msg, addr)  # PASS <password>
    def _handle_nick(self, msg, addr)  # NICK <nickname>
    def _handle_user(self, msg, addr)  # USER <username> <mode> <unused> :<realname>
    def _try_complete_registration(self, addr)  # Check if both NICK and USER have been received; if so, complete registration.
    def _handle_join(self, msg, addr)  # JOIN <channel>[,<channel>...]
    def _handle_part(self, msg, addr)  # PART <channel>[,<channel>...] [:<reason>]
    def _handle_privmsg(self, msg, addr)  # PRIVMSG <target> :<text>
    def _handle_wakeword(self, msg, addr)  # WAKEWORD ENABLE|DISABLE - Toggle wakeword-based message filtering for this client.
    def _should_forward_to_client(self, recipient_addr, message_text, sender_nick)  # Check whether a PRIVMSG should be forwarded to a specific recipient.
    def _broadcast_privmsg_filtered(self, channel, out_msg, message_text, sender_nick, exclude=None)  # Broadcast a PRIVMSG to channel members with wakeword filtering.
    def _handle_service_via_chatline(self, raw_line, addr, nick, channel=None)  # Handle service commands received via chatline (e.g., AI 1 agent assign...).
    def _send_notice(self, addr, text)  # Helper to send a NOTICE message to a client.
    def _handle_notice(self, msg, addr)  # NOTICE <target> :<text> — same as PRIVMSG but no auto-reply expected.
    def _handle_topic(self, msg, addr)  # TOPIC <channel> [:<new topic>]
    def _handle_invite(self, msg, addr)  # INVITE <nick> <channel>
    def _handle_names(self, msg, addr)  # NAMES [<channel>]
    def _handle_list(self, msg, addr)  # LIST — list all channels.
    def _handle_who(self, msg, addr)  # WHO <channel> — basic WHO reply.
    def _handle_whois(self, msg, addr)  # WHOIS <nick> — return information about a user per RFC 2812.
    def _handle_whowas(self, msg, addr)  # WHOWAS <nick> — return information about a disconnected user per RFC 2812.
    def _handle_oper(self, msg, addr)  # OPER <account> <password>
    def _handle_away(self, msg, addr)  # AWAY [:<message>]
    def _handle_mode(self, msg, addr)  # MODE <target> <modestring> [param1] [param2] ...
    def _handle_user_mode(self, msg, addr, nick, target_nick)  # Handle user MODE commands.
    def _handle_channel_mode(self, msg, addr, nick, chan_name)  # Parse and apply combined channel mode changes (up to 8 per command).
    def _handle_kick(self, msg, addr)  # KICK <channel> <nick> [:<reason>]
    def _handle_kill(self, msg, addr)  # KILL <nick> [:<reason>] — requires oper 'kill' flag.
    def _handle_connect(self, msg, addr)  # CONNECT <host> <port> [password] — Initiate S2S link. Requires 'connect' flag.
    def _handle_squit_cmd(self, msg, addr)  # SQUIT <server_id> [:<reason>] — Drop an S2S link. Requires 'squit' flag.
    def _handle_trust(self, msg, addr)  # TRUST <ADD|REMOVE|LIST> [nick_or_host] — Manage trusted hosts/nicks.
    def _handle_setmotd(self, msg, addr)  # SETMOTD :<new message of the day> — Requires 'setmotd' oper flag.
    def _handle_stats(self, msg, addr)  # STATS [letter] — Server statistics query. Requires 'stats' oper flag.
    def _handle_rehash(self, msg, addr)  # REHASH — no longer supported. opers.json is the sole authority.
    def _handle_shutdown(self, msg, addr)  # SHUTDOWN [:<reason>] — Gracefully shut down the server. Requires 'shutdown' flag.
    def _handle_localconfig(self, msg, addr)  # LOCALCONFIG <key> [value] — Read or set a local server config value.
    def _server_kill(self, target_nick, reason='Disconnected')  # Disconnect a client by nick. Cleans up channels, clients, registration,
    def _handle_nickserv(self, msg, addr)  # Handle PRIVMSG NickServ :COMMAND args — virtual NickServ service.
    def _nickserv_register(self, args, addr)  # REGISTER <password> — register your current nick with NickServ.
    def _nickserv_identify(self, args, addr)  # IDENTIFY <password> — identify as the owner of your current nick.
    def _nickserv_ghost(self, args, addr)  # GHOST <nickname> <password> — kill a ghost session to reclaim a nick.
    def _nickserv_info(self, args, addr)  # INFO <nickname> — show registration info for a nick.
    def _nickserv_drop(self, args, addr)  # DROP <password> — unregister your current nick.
    def _nickserv_notice(self, addr, text)  # Send a NOTICE from NickServ to a client.
    def _handle_chanserv(self, msg, addr)  # Handle PRIVMSG ChanServ :COMMAND args — virtual ChanServ service.
    def _chanserv_set(self, args, addr)  # SET <#chan> <option> <on/off>
    def _chanserv_register(self, args, addr)  # REGISTER <#chan> <topic>
    def _chanserv_op(self, args, addr)  # OP <#chan> <nick>
    def _chanserv_deop(self, args, addr)  # DEOP <#chan> <nick>
    def _chanserv_voice(self, args, addr)  # VOICE <#chan> <nick>
    def _chanserv_devoice(self, args, addr)  # DEVOICE <#chan> <nick>
    def _chanserv_ban(self, args, addr)  # BAN <#chan> <mask>
    def _chanserv_unban(self, args, addr)  # UNBAN <#chan> <mask>
    def _chanserv_info(self, args, addr)  # INFO <#chan>
    def _chanserv_list(self, args, addr)  # LIST
    def _chanserv_notice(self, addr, text)  # Send a NOTICE from ChanServ to a client.
    def _handle_botserv(self, msg, addr)  # Handle PRIVMSG BotServ :COMMAND args — virtual BotServ service.
    def _botserv_setlog(self, args, addr)  # SETLOG <botnick> <#chan> <log_file> [enable/disable]
    def _botserv_add(self, args, addr)  # ADD <botnick> <#chan> <password>
    def _botserv_del(self, args, addr)  # DEL <botnick> <#chan>
    def _botserv_list(self, args, addr)  # LIST [#chan]
    def _botserv_notice(self, addr, text)  # Send a NOTICE from BotServ to a client.
    def _chanserv_notice(self, addr, text)  # Send a NOTICE from ChanServ to a client.
    def _nickserv_notice(self, addr, text)  # Send a NOTICE from NickServ to a client.
    def _nickserv_enforce(self, addr, nick)  # Called by enforcement timer if client hasn't identified. Handles based on enforce_mode.
    def _handle_motd(self, msg, addr)  # MOTD — send the message of the day.
    def _handle_buffer(self, msg, addr)  # BUFFER <target> [full] — replay the chat buffer for a channel or PM target.
    def _send_buffer_replay(self, addr, nick, target, full_history=False)  # Read the buffer for *target* and send each line as a NOTICE to *addr*.
    def _is_authorized(self, nick, channel_name=None)  # Check if a nick is authorized (IRC operator or channel operator).
    def _maybe_replay_pm_buffer(self, recipient_nick, sender_nick)  # On first PM to *recipient_nick* from *sender_nick* in this session,
    def _handle_ping(self, msg, addr)  # PING :<token> -> PONG :<token>
    def _handle_pong(self, msg, addr)  # PONG — just update last_seen.
    def _handle_quit(self, msg, addr)  # QUIT [:<message>]
    def _handle_cap(self, msg, addr)  # CAP — capability negotiation (IRCv3). Respond with empty list.
    def _handle_cryptoinit(self, msg, addr)  # CRYPTOINIT DH <p> <g> <pub>
    def _handle_legacy_ident(self, msg, addr, raw_line)  # Convert legacy IDENT <name> [password] to NICK + USER registration.
    def _handle_legacy_rename(self, msg, addr, raw_line)  # Convert legacy RENAME <old> <new> to NICK change.
    def _handle_isop(self, msg, addr)  # ISOP <nick> — returns whether nick is an IRC operator.
    def _handle_wallops(self, msg, addr)  # WALLOPS :<message> — oper only, broadcasts to all opers.
    def _normalize_ban_mask(mask)  # Normalize a ban mask to nick!user@host format.
    def _match_ban_mask(mask, nick_user_host)  # Match a ban mask pattern against a nick!user@host string.
    def _is_banned(self, channel, nick, user, host)  # Check if a nick!user@host matches any ban in the channel's ban list.
    def _send_ban_list(self, addr, nick, chan_name, channel)  # Send RPL_BANLIST (367) entries followed by RPL_ENDOFBANLIST (368).
    def _get_nick(self, addr)  # Get the nick for an address.
    def _get_user(self, addr)  # Get the username for an address.
    def _is_registered(self, addr)  # Check if an address has completed IRC registration.
    def _get_client_channel(self, addr)  # Find the primary/current channel for a client.
    def _find_client_addr(self, nick)  # Find the address for a client by nick.
    def _send_numeric(self, addr, numeric, target_nick, text)  # Send a numeric reply to an address.
    def _send_names(self, addr, nick, channel)  # Send RPL_NAMREPLY + RPL_ENDOFNAMES for a channel.
    def _send_motd(self, addr, nick)  # Send MOTD as 375/372/376 numerics.
    def _update_last_seen(self, name, addr)  # Update the last_seen timestamp for an active client.
    def handle_service_command(self, line, addr, client_name)  # Legacy entry point for service commands.
    def _oper_notice(self, addr, text)  # Send a NOTICE to the requesting oper.
    def _require_oper(self, addr)  # Return nick if oper, else send ERR_NOPRIVILEGES and return None.
    def _require_admin(self, addr)  # Return nick if server admin (a/A flag), else deny.
    def _handle_setmotd(self, msg, addr)  # SETMOTD :<text>  — set Message of the Day (requires server admin).
    def _handle_trust(self, msg, addr)  # TRUST <subcommand> [args] — manage o-lines (oper credentials).
    def _trust_help(self, addr)
    def _trust_list(self, addr)
    def _trust_add(self, addr, args)
    def _trust_del(self, addr, args)
    def _trust_edit(self, addr, args)
    def _trust_addhost(self, addr, args)
    def _trust_delhost(self, addr, args)
    def _write_olines_conf(self, data)  # Rewrite olines.conf from current opers.json data (export only).
    def _handle_stats(self, msg, addr)  # STATS <letter> — server statistics (oper only).
    def _handle_rehash(self, msg, addr)  # REHASH — no longer supported. opers.json is the sole authority.
    def _handle_shutdown(self, msg, addr)  # SHUTDOWN [reason] — graceful server shutdown (requires server admin).
    def _handle_link(self, msg, addr)  # LINK <server> [port] — initiate S2S link.
    def _handle_relink(self, msg, addr)  # RELINK <server> — reconnect a dropped S2S link.
    def _handle_delink(self, msg, addr)  # DELINK <server> [reason] — drop S2S link (alias for SQUIT).
    def _handle_help(self, msg, addr)  # HELP — show available commands based on caller's oper flags.
    def _handle_localconfig(self, msg, addr)  # LOCALCONFIG <show|list|get|set|del> [key] [value]

── irc/packages/csc-service/csc_service/server/server_s2s.py ──
# Server-to-Server (S2S) linking protocol for CSC IRC server federation.
  S2S_CRLF = b'\r\n'
  S2S_MAX_LINE = 8192
  class ServerLink:  # Represents a single UDP connection to a peer CSC server with DH encryption.
    def __init__(self, local_server, remote_host, remote_port, password, remote_server_id=None, sock=None)  # Initialize a server link.
    def connect(self)  # Establish UDP connection to remote server and initiate DH key exchange.
    def _initiate_dh_exchange(self)  # Send CRYPTOINIT DH message to initiate key exchange.
    def _handle_dh_reply(self, pubkey_hex)  # Process CRYPTOINIT DHREPLY message and derive AES key.
    def _send_dh_reply(self, pubkey_hex)  # Process incoming CRYPTOINIT DH and send DHREPLY with AES derivation.
    def authenticate(self)  # Exchange SLINK/SLINKACK handshake after DH key exchange.
    def handle_inbound_handshake(self)  # Handle authentication for an inbound (accepted) connection.
    def start_reader(self, callback)  # Start a background thread that reads S2S messages and calls callback.
    def _reader_loop(self, callback)  # Background loop reading UDP datagrams and processing S2S messages.
    def send_message(self, command, *args)  # Send an S2S command to the remote server (encrypted if key available).
    def send_raw(self, line)  # Send a raw line to the remote server (encrypted if key available).
    def is_connected(self)  # Check if this link is alive and authenticated.
    def close(self)  # Gracefully close the link.
    def _recv_line(self, timeout=None)  # Read one CRLF-terminated line from the socket.
    def _get_local_server_id(self)  # Return the local server's unique ID.
    def _log(self, message)  # Log via the local server's logger.
  class ServerNetwork:  # Manages all linked servers and network-wide operations.
    def __init__(self, local_server)  # Initialize the server network manager.
    def start_listener(self)  # Start the UDP listener for inbound S2S connections with DH encryption.
    def _receive_loop(self)  # Receive inbound S2S UDP datagrams from peers with DH and SLINK auth.
    def _handle_inbound_link(self, link)  # Handle a newly established inbound UDP S2S link.
    def link_to(self, host, port, password=None)  # Initiate an outbound link to a remote server.
    def get_peer_servers(self)  # List all connected peer server IDs.
    def get_link(self, server_id)  # Get the ServerLink for a specific peer.
    def broadcast_to_network(self, command, args_str='', exclude_server=None)  # Send an S2S command to all connected peers.
    def get_user_from_network(self, nick)  # Find a user on any server in the network.
    def get_channel_from_network(self, channel)  # Find a channel on any server in the network.
    def route_message(self, source_nick, target, text, exclude_server=None)  # Route a PRIVMSG/NOTICE across the network.
    def sync_line(self, target_nick, line, exclude_server=None)  # Route a raw IRC line to a specific user on the network.
    def sync_user_join(self, nick, host, modes, channel=None, exclude_server=None)  # Notify the network that a user joined/connected.
    def sync_user_quit(self, nick, reason='', exclude_server=None)  # Notify the network that a user disconnected.
    def sync_user_part(self, nick, channel, reason='', exclude_server=None)  # Notify the network that a user parted a channel.
    def sync_nick_change(self, old_nick, new_nick, exclude_server=None)  # Notify the network that a user changed their nickname.
    def sync_channel(self, channel_name, modes_str, members_json, exclude_server=None)  # Broadcast channel state to the network.
    def sync_topic(self, channel_name, topic, exclude_server=None)  # Broadcast channel topic to the network.
    def sync_channel_state(self, chan_name, exclude_server=None)  # Helper to sync current state of a local channel to the network.
    def _send_full_sync(self, link)  # Send complete local state to a newly linked peer.
    def _dispatch_s2s_message(self, link, command, rest)  # Route an incoming S2S command to the appropriate handler.
    def _handle_syncuser(self, link, rest)  # Handle SYNCUSER: add/update a remote user in tracking.
    def _handle_synpart(self, link, rest)  # Handle SYNPART: remote user leaves a channel.
    def _handle_syncnick(self, link, rest)  # Handle SYNCNICK: remote user changes nickname.
    def _handle_syncchan(self, link, rest)  # Handle SYNCCHAN: merge remote channel state.
    def _handle_synctopic(self, link, rest)  # Handle SYNCTOPIC: remote channel topic update.
    def _handle_syncmsg(self, link, rest)  # Handle SYNCMSG: deliver a message from the network locally.
    def _handle_syncline(self, link, rest)  # Handle SYNCLINE: deliver a raw IRC line to a local user.
    def _handle_desync(self, link, rest)  # Handle DESYNC: remove a nick or channel from remote tracking.
    def _handle_squit(self, link, rest)  # Handle SQUIT: a server is disconnecting.
    def _handle_error(self, link, rest)  # Handle ERROR message from a peer.
    def _handle_link_lost(self, link)  # Called when a link's reader thread detects a disconnect.
    def _remove_server_state(self, server_id)  # Remove all remote state belonging to a disconnected server.
    def _rename_local_user(self, old_nick, new_nick)  # Rename a local user due to nick collision.
    def shutdown(self)  # Shut down all S2S connections and the listener.
    def _get_local_server_id(self)  # Return the local server's unique ID.
    def _log(self, message)  # Log via the local server's logger.

── irc/packages/csc-service/csc_service/server/service.py ──
  class Service(Network):
    def __init__(self, server_instance=None)
    def default(self, *args)  # Default command handler for a service.
    def handle_command(self, class_name_raw, method_name_raw, args, source_name, source_address)  # Executes a command by dynamically loading a service module.

── irc/packages/csc-service/csc_service/server/version.py ──
  class Version(Data):  # Extends the Data class.
    def __init__(self)  # Initializes the Version class.
    def get_version_dir_for_file(self, filepath: str) -> Path  # Generates a unique version history directory for a given file.
    def _get_version_info(self, file_backup_dir: Path) -> dict  # Reads version metadata from the 'versions.json' file for a specific file.
    def _write_version_info(self, file_backup_dir: Path, version_info: dict)  # Writes updated version info back to the metadata file.
    def restore_version(self, filepath: str, version: str='latest')  # Restores a file to a specific version from its backup history.
    def create_new_version(self, filepath: str)  # Creates a new, sequentially numbered version of a file.
