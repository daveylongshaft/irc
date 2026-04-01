"""Nick collision resolution for S2S-linked IRC servers.

When two servers link and both have a user with the same nick, one must be
renamed. The rules follow standard IRC collision resolution:
  1. The user who connected LATER loses (older connection wins).
  2. If timestamps are equal, the server with the lexicographically
     lower server_id wins.
  3. The loser gets renamed to nick_servershort (e.g. davey_ef6e).
"""


def detect_collision(nick, local_nicks, remote_nicks):
    """Check if a nick exists in both local and remote user sets.

    Args:
        nick: The nickname to check (case-insensitive).
        local_nicks: Set or list of local nicknames.
        remote_nicks: Set or list of remote nicknames.

    Returns:
        True if the nick exists in both sets, False otherwise.
    """
    nick_lower = nick.lower()
    local_lower = {n.lower() for n in local_nicks}
    remote_lower = {n.lower() for n in remote_nicks}
    return nick_lower in local_lower and nick_lower in remote_lower


def resolve_collision(nick, server_a_id, server_b_id,
                      local_connect_time=0, remote_connect_time=0):
    """Determine which server's user wins and generate a new nick for the loser.

    Args:
        nick: The colliding nickname.
        server_a_id: Server ID of the first server (the one calling this).
        server_b_id: Server ID of the second server.
        local_connect_time: Unix timestamp when server_a's user connected.
        remote_connect_time: Unix timestamp when server_b's user connected.

    Returns:
        (winner_server_id, new_nick_for_loser) tuple.
        winner_server_id is the server whose user keeps the nick.
        new_nick_for_loser is the renamed nick for the losing user.
    """
    # Older connection wins (lower timestamp = connected first)
    if local_connect_time < remote_connect_time:
        winner = server_a_id
        loser = server_b_id
    elif remote_connect_time < local_connect_time:
        winner = server_b_id
        loser = server_a_id
    else:
        # Equal timestamps: lower server_id wins
        if server_a_id < server_b_id:
            winner = server_a_id
            loser = server_b_id
        else:
            winner = server_b_id
            loser = server_a_id

    # Generate new nick: nick_shortid (e.g. davey_ef6e)
    short = loser.split(".")[-1] if "." in loser else loser[:4]
    new_nick = f"{nick}_{short}"

    # Truncate to IRC nick length limit (30 chars)
    if len(new_nick) > 30:
        new_nick = new_nick[:30]

    return (winner, new_nick)
