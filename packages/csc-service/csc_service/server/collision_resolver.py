"""
Nick collision detection and resolution for S2S federation.

When two servers merge and discover duplicate nicknames, this module
determines which user keeps the nick and generates a new nick for the loser.

Resolution priority:
  1. Older connection wins (lower connect_time)
  2. Hash-based tiebreaker if timestamps are equal
  3. Oper override (handled by caller)
"""

import hashlib
import time


def detect_collision(nick, local_server_id, remote_server_id,
                     local_users=None, remote_nick_list=None):
    """Check if a nick exists on both local and remote servers.

    Args:
        nick: Nickname to check.
        local_server_id: ID of the local server.
        remote_server_id: ID of the remote server.
        local_users: Dict of local users {nick_lower: info} (optional).
        remote_nick_list: List of remote nicks (optional).

    Returns:
        True if collision detected, False otherwise.
    """
    if local_users is None or remote_nick_list is None:
        return False
    nick_lower = nick.lower()
    return nick_lower in local_users and nick_lower in [n.lower() for n in remote_nick_list]


def resolve_collision(nick, server_a_id, server_b_id,
                      local_connect_time=None, remote_connect_time=None):
    """Determine which server keeps the nick and generate a new nick for the loser.

    Resolution rules:
      1. The user with the older (lower) connect_time keeps the nick.
      2. If connect times are equal, use hash-based tiebreaker:
         hash(nick + server_id) determines winner - lower hash wins.
      3. The losing user gets a generated nick: nick_XXXXX (5 hex chars).

    Args:
        nick: The contested nickname.
        server_a_id: First server's ID (typically local).
        server_b_id: Second server's ID (typically remote).
        local_connect_time: Epoch timestamp of user A's connection.
        remote_connect_time: Epoch timestamp of user B's connection.

    Returns:
        Tuple of (winner_server_id, loser_new_nick).
        winner_server_id is the ID of the server whose user keeps the nick.
        loser_new_nick is the generated nick for the other user.
    """
    now = int(time.time())
    ts_a = local_connect_time if local_connect_time is not None else now
    ts_b = remote_connect_time if remote_connect_time is not None else now

    # Rule 1: Older connection wins
    if ts_a < ts_b:
        winner = server_a_id
    elif ts_b < ts_a:
        winner = server_b_id
    else:
        # Rule 2: Server ID tiebreaker (lexicographical)
        winner = server_a_id if server_a_id < server_b_id else server_b_id

    # Generate new nick for the loser
    loser_new_nick = generate_collision_nick(nick)

    return (winner, loser_new_nick)


def generate_collision_nick(nick):
    """Generate a unique replacement nick for a collision loser.

    Creates a nick by appending a 5-char hex suffix derived from the
    current timestamp, ensuring it's different each time.

    Args:
        nick: Original nickname.

    Returns:
        New nickname string in format: nick_XXXXX (truncated to 9+5+1=15 chars max).
    """
    suffix = hashlib.md5(f"{nick}{time.time()}".encode()).hexdigest()[:5]
    # IRC nicks typically max at 15 chars; truncate base nick if needed
    max_base = 9  # 9 + 1 ('_') + 5 (suffix) = 15
    base = nick[:max_base]
    return f"{base}_{suffix}"
