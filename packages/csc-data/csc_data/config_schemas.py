
"""
JSON Schemas for csc-service configuration files.
"""

SETTINGS_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "version": {"type": "number", "minimum": 1.0},
        "server_name": {"type": "string"},
        "port": {"type": "integer", "minimum": 1, "maximum": 65535},
        "max_clients": {"type": "integer", "minimum": 1},
        "motd": {"type": "string"},
        "timeout": {"type": "integer", "minimum": 1},
        "nickserv": {
            "type": "object",
            "properties": {
                "enforce_timeout": {"type": "integer"},
                "enforce_mode": {"type": "string", "enum": ["disconnect", "kill", "none"]}
            }
        }
    },
    "required": ["version", "server_name", "port"],
    "additionalProperties": True
}

PLATFORM_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "version": {"type": "number", "minimum": 1.0},
        "csc_root": {"type": "string"},
        "temp_path": {"type": "string"},
        "log_path": {"type": "string"},
    },
    "required": ["version", "csc_root"],
    "additionalProperties": True
}

OPERS_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "version": {"type": "number", "const": 2},
        "protect_local_opers": {"type": "boolean"},
        "active_opers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "nick": {"type": "string"},
                    "account": {"type": "string"},
                    "flags": {"type": "string"}
                },
                "required": ["nick", "account", "flags"]
            }
        },
        "olines": {
            "type": "object",
            "patternProperties": {
                "^[a-zA-Z0-9_`{\[\]}\|\^\-]+$": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "user": {"type": "string"},
                            "password": {"type": "string"},
                            "servers": {"type": "array", "items": {"type": "string"}},
                            "host_masks": {"type": "array", "items": {"type": "string"}},
                            "flags": {"type": "string"},
                            "comment": {"type": "string"}
                        },
                        "required": ["user", "password", "flags"]
                    }
                }
            }
        }
    },
    "required": ["version", "olines"]
}


USERS_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "version": {"type": "number", "const": 1},
        "users": {
            "type": "object",
            "patternProperties": {
                "^[a-zA-Z0-9_`{\[\]}\|\^\-]+$": {
                    "type": "object",
                    "properties": {
                        "password_hash": {"type": "string"},
                        "email": {"type": "string"},
                        "registered": {"type": "boolean"}
                    }
                }
            }
        }
    },
    "required": ["version", "users"]
}

CHANNELS_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "version": {"type": "number", "const": 1},
        "channels": {
            "type": "object",
            "patternProperties": {
                "^#.*$": {
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string"},
                        "modes": {"type": "array", "items": {"type": "string"}},
                        "members": {
                            "type": "object",
                            "patternProperties": {
                                "^.*$": {
                                    "type": "object",
                                    "properties": {
                                        "modes": {"type": "array", "items": {"type": "string"}}
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    },
    "required": ["version", "channels"]
}

BANS_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "version": {"type": "number", "const": 1},
        "channel_bans": {
            "type": "object",
            "patternProperties": {
                "^#.*$": {
                    "type": "array",
                    "items": {
                        "type": "string"
                    }
                }
            }
        }
    },
    "required": ["version"]
}

NICKSERV_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "version": {"type": "number", "const": 1},
        "nicks": {
            "type": "object",
            "patternProperties": {
                "^.*$": {
                    "type": "object",
                    "properties": {
                        "nick": {"type": "string"},
                        "password": {"type": "string"},
                        "registered_by": {"type": "string"},
                        "registered_at": {"type": "number"}
                    },
                    "required": ["nick", "password"]
                }
            }
        }
    },
    "required": ["version", "nicks"]
}

CHANSERV_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "version": {"type": "number", "const": 1},
        "channels": {
            "type": "object",
            "patternProperties": {
                "^#.*$": {
                    "type": "object"
                }
            }
        }
    },
    "required": ["version", "channels"]
}


BOTSERV_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "version": {"type": "number", "const": 1},
        "bots": {
            "type": "object",
            "patternProperties": {
                "^.*:.*$": {
                    "type": "object"
                }
            }
        }
    },
    "required": ["version", "bots"]
}

HISTORY_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "version": {"type": "number", "const": 1},
        "disconnections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "nick": {"type": "string"},
                    "user": {"type": "string"},
                    "realname": {"type": "string"},
                    "host": {"type": "string"},
                    "quit_time": {"type": "number"},
                    "quit_reason": {"type": "string"}
                },
                "required": ["nick", "user", "host", "quit_time"]
            }
        }
    },
    "required": ["version", "disconnections"]
}

SCHEMAS = {
    "settings": SETTINGS_SCHEMA,
    "platform": PLATFORM_SCHEMA,
    "opers": OPERS_SCHEMA,
    "users": USERS_SCHEMA,
    "channels": CHANNELS_SCHEMA,
    "bans": BANS_SCHEMA,
    "nickserv": NICKSERV_SCHEMA,
    "chanserv": CHANSERV_SCHEMA,
    "botserv": BOTSERV_SCHEMA,
    "history": HISTORY_SCHEMA
}
