# Configuration File Schemas

This document describes the JSON schema for each of the configuration files used by the CSC server.

## `settings.json`

Server-wide settings.

- `version` (number, required): Schema version.
- `server_name` (string, required): The name of the server.
- `port` (integer, required): The port for the server to listen on.
- `max_clients` (integer): Maximum number of clients.
- `motd` (string): Message of the day.
- `timeout` (integer): Client inactivity timeout in seconds.
- `nickserv` (object): NickServ configuration.
  - `enforce_timeout` (integer): Timeout for NickServ enforcement.
  - `enforce_mode` (string): "disconnect", "kill", or "none".

## `platform.json`

Platform-specific configuration.

- `version` (number, required): Schema version.
- `csc_root` (string, required): The root directory of the CSC installation.
- `temp_path` (string): Path to the temporary directory.
- `log_path` (string): Path to the log directory.

## `opers.json`

Operator credentials and permissions.

- `version` (number, required): Schema version.
- `protect_local_opers` (boolean): Whether remote opers without O flag can KILL local opers.
- `active_opers` (array): List of active operators.
- `olines` (object): Operator lines defining permissions.

## `users.json`

User database.

- `version` (number, required): Schema version.
- `users` (object): A dictionary of users.

## `channels.json`

Persistent channel data.

- `version` (number, required): Schema version.
- `channels` (object): A dictionary of channels.

## `bans.json`

Ban lists.

- `version` (number, required): Schema version.
- `channel_bans` (object): A dictionary of channel bans.

## `nickserv.json`

NickServ registration data.

- `version` (number, required): Schema version.
- `nicks` (object): A dictionary of registered nicks.

## `chanserv.json`

ChanServ registration data.

- `version` (number, required): Schema version.
- `channels` (object): A dictionary of registered channels.

## `botserv.json`

BotServ registration data.

- `version` (number, required): Schema version.
- `bots` (object): A dictionary of registered bots.

## `history.json`

Message history.

- `version` (number, required): Schema version.
- `disconnections` (array): A list of disconnection events.
