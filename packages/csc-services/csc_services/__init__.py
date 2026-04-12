from csc_services.service import Service
from csc_services.irc import IRCMessage, SERVER_NAME, format_irc_message, numeric_reply, parse_irc_message
from csc_platform import Platform

PROJECT_ROOT = Platform.PROJECT_ROOT

__all__ = [
    "IRCMessage",
    "PROJECT_ROOT",
    "SERVER_NAME",
    "Service",
    "format_irc_message",
    "numeric_reply",
    "parse_irc_message",
]
