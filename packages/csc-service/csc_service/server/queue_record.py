"""QueueRecord: frozen dataclass for the unified S2S message queue."""

from dataclasses import dataclass


@dataclass(frozen=True)
class QueueRecord:
    """A single event flowing through the unified S2S message queue.

    Attributes:
        source_server: Server ID that originated the event (e.g. "haven.4346").
        source_client: Full nick!user@host prefix of the originating client.
        command: IRC command (PRIVMSG, NOTICE, JOIN, PART, KICK, QUIT, MODE,
                 NICK, TOPIC, INVITE, AWAY, WALLOPS).
        target: Target channel ("#channel"), nick, or "*" for global events.
        content: Message text, mode args, kick reason, etc.
        origin_local: True if this event originated on this server.
                      False if received from S2S (prevents re-replication).
        via_link: Server ID of the direct peer that sent this record.
                  Empty string for locally originated events. Used to
                  prevent echo (don't send back to the link it came from)
                  and for chain-relay topology tracking.
    """
    source_server: str
    source_client: str
    command: str
    target: str
    content: str = ""
    origin_local: bool = True
    via_link: str = ""
