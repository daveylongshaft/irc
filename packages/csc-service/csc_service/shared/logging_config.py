"""
Structured logging configuration for CSC IRC Server.

Provides JSON-formatted file logging with rotation and human-readable console output.
Supports standard log fields: timestamp, level, operation, user, channel, result, message.

Usage:
    from csc_service.shared.logging_config import get_logger
    
    logger = get_logger('server')
    logger.info("Server started", extra={
        'operation': 'START',
        'result': 'OK'
    })
"""

import logging
import logging.handlers
import json
import os
from pathlib import Path
from datetime import datetime


class StructuredFormatter(logging.Formatter):
    """
    Custom formatter that outputs structured JSON logs.
    
    Standard fields:
    - timestamp: ISO 8601 timestamp
    - level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    - operation: Command/operation being performed
    - user: Nick or addr of user involved
    - channel: Channel name (if applicable)
    - result: OK, BLOCKED, ERROR, etc.
    - message: Human-readable description
    - Additional fields from 'extra' parameter
    """
    
    def format(self, record):
        """Format log record as JSON."""
        log_data = {
            'timestamp': datetime.utcfromtimestamp(record.created).isoformat() + 'Z',
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage()
        }
        
        # Add standard fields from extra parameter if present
        for field in ['operation', 'user', 'channel', 'result', 'reason', 'addr', 'nick']:
            if hasattr(record, field):
                log_data[field] = getattr(record, field)
        
        # Add any other extra fields
        if hasattr(record, '__dict__'):
            for key, value in record.__dict__.items():
                if key not in ['name', 'msg', 'args', 'created', 'filename', 'funcName',
                               'levelname', 'levelno', 'lineno', 'module', 'msecs',
                               'message', 'pathname', 'process', 'processName',
                               'relativeCreated', 'thread', 'threadName', 'exc_info',
                               'exc_text', 'stack_info', 'operation', 'user', 'channel',
                               'result', 'reason', 'addr', 'nick', 'logger']:
                    if not key.startswith('_'):
                        log_data[key] = value
        
        return json.dumps(log_data)


class ConsoleFormatter(logging.Formatter):
    """
    Human-readable console formatter.
    
    Format: YYYY-MM-DD HH:MM:SS [LEVEL] OPERATION: message
    """
    
    def format(self, record):
        """Format log record for console output."""
        timestamp = datetime.fromtimestamp(record.created).strftime('%Y-%m-%d %H:%M:%S')
        level = record.levelname
        operation = getattr(record, 'operation', record.name)
        message = record.getMessage()
        
        return f"{timestamp} [{level}] {operation}: {message}"


def get_logger(name='csc_irc', config=None):
    """
    Get or create a configured logger instance.
    
    Args:
        name (str): Logger name, typically the module or component name
        config (dict): Optional configuration override with keys:
            - level: Log level (default: INFO)
            - max_bytes: Max log file size before rotation (default: 10MB)
            - backup_count: Number of rotated files to keep (default: 5)
            - json_logs: Enable JSON file logging (default: True)
            - log_dir: Directory for log files (default: logs/)
    
    Returns:
        logging.Logger: Configured logger instance
    """
    # Default configuration
    default_config = {
        'level': 'INFO',
        'max_bytes': 10 * 1024 * 1024,  # 10MB
        'backup_count': 5,
        'json_logs': True,
        'log_dir': 'logs'
    }
    
    if config:
        default_config.update(config)
    
    config = default_config
    
    # Get or create logger
    logger = logging.getLogger(name)
    
    # Only configure if not already configured
    if logger.handlers:
        return logger
    
    # Set log level
    level = getattr(logging, config['level'].upper(), logging.INFO)
    logger.setLevel(level)
    
    # Ensure log directory exists
    log_dir = Path(config['log_dir'])
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # Console handler (human-readable)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(ConsoleFormatter())
    logger.addHandler(console_handler)
    
    # File handler (JSON, rotated) - only if json_logs enabled
    if config['json_logs']:
        json_log_file = log_dir / f"{name}.json"
        file_handler = logging.handlers.RotatingFileHandler(
            str(json_log_file),
            maxBytes=config['max_bytes'],
            backupCount=config['backup_count']
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(StructuredFormatter())
        logger.addHandler(file_handler)
    
    # Prevent propagation to root logger
    logger.propagate = False
    
    return logger


def load_logging_config(settings_path='etc/settings.json'):
    """
    Load logging configuration from settings file.
    
    Args:
        settings_path (str): Path to settings JSON file
    
    Returns:
        dict: Logging configuration or default config
    """
    try:
        if os.path.exists(settings_path):
            with open(settings_path, 'r') as f:
                settings = json.load(f)
                return settings.get('logging', {})
    except Exception as e:
        print(f"Warning: Could not load logging config from {settings_path}: {e}")
    
    return {}


# Global logger cache to avoid duplicate configuration
_loggers = {}


def get_configured_logger(name='csc_irc', settings_path='etc/settings.json'):
    """
    Get a logger configured from settings file.
    
    Args:
        name (str): Logger name
        settings_path (str): Path to settings file
    
    Returns:
        logging.Logger: Configured logger
    """
    if name not in _loggers:
        config = load_logging_config(settings_path)
        _loggers[name] = get_logger(name, config)
    
    return _loggers[name]


if __name__ == '__main__':
    # Test the logging configuration
    logger = get_logger('test')
    
    logger.debug("Debug message", extra={'operation': 'TEST', 'result': 'OK'})
    logger.info("Info message", extra={'operation': 'TEST', 'user': 'alice', 'result': 'OK'})
    logger.warning("Warning message", extra={'operation': 'FILE_UPLOAD', 'user': 'bob', 'result': 'BLOCKED'})
    logger.error("Error message", extra={'operation': 'JOIN', 'channel': '#test', 'result': 'ERROR'})
    
    print("\n=== Log files created in logs/ directory ===")
    print("View JSON logs: cat logs/test.json | python -m json.tool")
    print("Filter blocked operations: python -m json.tool logs/test.json | grep -A5 'BLOCKED'")
