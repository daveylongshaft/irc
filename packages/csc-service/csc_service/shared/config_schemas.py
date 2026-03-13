"""
JSON Schemas for csc-service configuration files.
"""

# Schema for settings.json
SETTINGS_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "version": {"type": "number", "minimum": 1.0},
        "server_name": {"type": "string"},
        "port": {"type": "integer", "minimum": 1, "maximum": 65535},
        "max_clients": {"type": "integer", "minimum": 1},
        "motd": {"type": "string"},
        "timeout": {"type": "integer", "minimum": 1}
    },
    "required": ["version", "server_name", "port"],
    "additionalProperties": True
}

# Schema for platform.json
PLATFORM_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "version": {"type": "number", "minimum": 1.0},
        "csc_root": {"type": "string"},
        "temp_path": {"type": "string"},
        "log_path": {"type": "string"}
    },
    "required": ["version", "csc_root"],
    "additionalProperties": True
}

# Schema for opers.json
OPERS_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "version": {"type": "number", "minimum": 1.0},
        "olines": {
            "type": "object",
            "patternProperties": {
                "^[a-zA-Z0-9_`{\[\]}\|\^\-]+$": {
                    "type": "object",
                    "properties": {
                        "password": {"type": "string"},
                        "hosts": {
                            "type": "array",
                            "items": {"type": "string"}
                        },
                        "flags": {"type": "string"}
                    },
                    "required": ["password", "hosts", "flags"]
                }
            }
        }
    },
    "required": ["version", "olines"],
    "additionalProperties": True
}

# Schema for users.json
USERS_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "version": {"type": "number", "minimum": 1.0},
        "users": {
            "type": "object",
            "patternProperties": {
                "^[a-zA-Z0-9_`{\[\]}\|\^\-]+$": {
                    "type": "object",
                    "properties": {
                        "password": {"type": "string"},
                        "email": {"type": "string", "format": "email"},
                        "registered": {"type": "number"}
                    },
                    "required": ["password"]
                }
            }
        }
    },
    "required": ["version"],
    "additionalProperties": True
}

# Schema for channels.json
CHANNELS_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "version": {"type": "number", "minimum": 1.0},
        "channels": {
            "type": "object",
            "patternProperties": {
                "^#.*$": {
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string"},
                        "modes": {"type": "string"},
                        "members": {
                            "type": "array",
                            "items": {"type": "string"}
                        },
                        "bans": {
                            "type": "array",
                            "items": {"type": "string"}
                        }
                    },
                    "required": ["topic", "modes", "members", "bans"]
                }
            }
        }
    },
    "required": ["version", "channels"],
    "additionalProperties": True
}

# Schema for bans.json
BANS_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "version": {"type": "number", "minimum": 1.0},
        "bans": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "mask": {"type": "string"},
                    "reason": {"type": "string"},
                    "expires": {"type": "number"},
                    "set_by": {"type": "string"}
                },
                "required": ["mask", "reason", "expires", "set_by"]
            }
        }
    },
    "required": ["version", "bans"],
    "additionalProperties": True
}

# Schema for nickserv.json
NICKSERV_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "version": {"type": "number", "minimum": 1.0},
        "enabled": {"type": "boolean"},
        "config": {"type": "object"}
    },
    "required": ["version", "enabled"],
    "additionalProperties": True
}

# Schema for chanserv.json
CHANSERV_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "version": {"type": "number", "minimum": 1.0},
        "enabled": {"type": "boolean"},
        "config": {"type": "object"}
    },
    "required": ["version", "enabled"],
    "additionalProperties": True
}

# Schema for botserv.json
BOTSERV_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "version": {"type": "number", "minimum": 1.0},
        "enabled": {"type": "boolean"},
        "config": {"type": "object"}
    },
    "required": ["version", "enabled"],
    "additionalProperties": True
}

# Schema for history.json
HISTORY_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "version": {"type": "number", "minimum": 1.0},
        "history": {
            "type": "object",
            "patternProperties": {
                "^[a-zA-Z0-9_`{\[\]}\|\^\-]+$": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "user": {"type": "string"},
                            "host": {"type": "string"},
                            "realname": {"type": "string"},
                            "quit_time": {"type": "number"},
                            "quit_message": {"type": "string"}
                        },
                        "required": ["user", "host", "realname", "quit_time", "quit_message"]
                    }
                }
            }
        }
    },
    "required": ["version", "history"],
    "additionalProperties": True
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
    "history": HISTORY_SCHEMA,
}
