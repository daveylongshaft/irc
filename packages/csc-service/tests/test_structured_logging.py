"""
Test structured logging functionality.

Verifies that:
1. Structured logger is properly configured
2. JSON logs are written with correct fields
3. Log rotation works correctly
4. Console output is human-readable
"""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from csc_service.shared.logging_config import get_logger, get_configured_logger


class TestStructuredLogging(unittest.TestCase):
    """Test cases for structured logging."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create temporary directory for test logs
        self.test_dir = tempfile.mkdtemp()
        self.config = {
            'level': 'DEBUG',
            'max_bytes': 1024,  # Small size for rotation testing
            'backup_count': 3,
            'json_logs': True,
            'log_dir': self.test_dir
        }
    
    def tearDown(self):
        """Clean up test fixtures."""
        # Remove temporary directory
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
    
    def test_logger_creation(self):
        """Test that logger can be created with custom config."""
        logger = get_logger('test_logger', self.config)
        self.assertIsNotNone(logger)
        self.assertEqual(logger.name, 'test_logger')
    
    def test_json_log_format(self):
        """Test that JSON logs contain expected fields."""
        logger = get_logger('test_json', self.config)
        
        # Log a message with structured fields
        logger.info("Test message", extra={
            'operation': 'TEST_OP',
            'user': 'alice',
            'channel': '#test',
            'result': 'OK'
        })
        
        # Read the JSON log file
        log_file = Path(self.test_dir) / 'test_json.json'
        self.assertTrue(log_file.exists())
        
        with open(log_file, 'r') as f:
            log_line = f.readline()
            log_entry = json.loads(log_line)
        
        # Verify required fields
        self.assertIn('timestamp', log_entry)
        self.assertIn('level', log_entry)
        self.assertIn('message', log_entry)
        self.assertEqual(log_entry['level'], 'INFO')
        self.assertEqual(log_entry['message'], 'Test message')
        
        # Verify structured fields
        self.assertEqual(log_entry['operation'], 'TEST_OP')
        self.assertEqual(log_entry['user'], 'alice')
        self.assertEqual(log_entry['channel'], '#test')
        self.assertEqual(log_entry['result'], 'OK')
    
    def test_log_levels(self):
        """Test that different log levels work correctly."""
        logger = get_logger('test_levels', self.config)
        
        logger.debug("Debug message", extra={'operation': 'DEBUG_TEST'})
        logger.info("Info message", extra={'operation': 'INFO_TEST'})
        logger.warning("Warning message", extra={'operation': 'WARN_TEST'})
        logger.error("Error message", extra={'operation': 'ERROR_TEST'})
        
        # Read all log entries
        log_file = Path(self.test_dir) / 'test_levels.json'
        with open(log_file, 'r') as f:
            lines = f.readlines()
        
        self.assertEqual(len(lines), 4)
        
        # Verify levels
        levels = [json.loads(line)['level'] for line in lines]
        self.assertEqual(levels, ['DEBUG', 'INFO', 'WARNING', 'ERROR'])
    
    def test_log_rotation(self):
        """Test that log rotation works when file size exceeds limit."""
        logger = get_logger('test_rotation', self.config)
        
        # Generate enough logs to trigger rotation
        for i in range(100):
            logger.info(f"Log message {i}" * 10, extra={'operation': 'ROTATION_TEST'})
        
        # Check that rotation occurred (backup files created)
        log_dir = Path(self.test_dir)
        log_files = list(log_dir.glob('test_rotation.json*'))
        
        # Should have main file plus at least one backup
        self.assertGreater(len(log_files), 1)
    
    def test_security_logging(self):
        """Test logging of security events with proper fields."""
        logger = get_logger('test_security', self.config)
        
        # Simulate a blocked file upload
        logger.warning("File upload blocked", extra={
            'operation': 'FILE_UPLOAD',
            'user': 'bob@192.168.1.100',
            'result': 'BLOCKED',
            'reason': 'unauthorized'
        })
        
        # Read and verify
        log_file = Path(self.test_dir) / 'test_security.json'
        with open(log_file, 'r') as f:
            log_entry = json.loads(f.readline())
        
        self.assertEqual(log_entry['operation'], 'FILE_UPLOAD')
        self.assertEqual(log_entry['result'], 'BLOCKED')
        self.assertEqual(log_entry['reason'], 'unauthorized')
        self.assertIn('bob', log_entry['user'])
    
    def test_irc_command_logging(self):
        """Test logging of IRC commands."""
        logger = get_logger('test_irc', self.config)
        
        # Log a JOIN command
        logger.info("User joined channel", extra={
            'operation': 'JOIN',
            'user': 'alice',
            'channel': '#general',
            'result': 'OK'
        })
        
        # Log a PRIVMSG
        logger.info("Message sent", extra={
            'operation': 'PRIVMSG',
            'user': 'alice',
            'channel': '#general',
            'result': 'OK'
        })
        
        # Read and verify
        log_file = Path(self.test_dir) / 'test_irc.json'
        with open(log_file, 'r') as f:
            lines = f.readlines()
        
        self.assertEqual(len(lines), 2)
        
        join_log = json.loads(lines[0])
        msg_log = json.loads(lines[1])
        
        self.assertEqual(join_log['operation'], 'JOIN')
        self.assertEqual(msg_log['operation'], 'PRIVMSG')
    
    def test_backwards_compatibility(self):
        """Test that legacy logging still works."""
        from csc_service.server.log import Log
        
        # Create a Log instance
        log_instance = Log()
        
        # Should have structured logger
        self.assertIsNotNone(log_instance._structured_logger)
        
        # Legacy log() should work
        log_instance.log("Test legacy message")
        
        # Structured log() with extra fields should work
        log_instance.log("Test structured message", level='INFO', 
                        operation='TEST', result='OK')


if __name__ == '__main__':
    unittest.main()
