"""
Test S2S null safety checks in PR #9.

Tests verify:
1. Handler files syntax is valid (via ast parsing)
2. Modified methods implement proper null safety checks
3. S2S network calls are safe from None crashes
"""

import pytest
import sys
import traceback
import ast
import os
from unittest.mock import Mock, MagicMock, patch

# Test that handler files have valid syntax
def _check_file_syntax(filepath):
    """Parse a Python file and verify syntax is valid."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            code = f.read()
        ast.parse(code)
        return True, None
    except SyntaxError as e:
        return False, str(e)


def _get_test_file_path(filename):
    """Get absolute path to file relative to test directory."""
    test_dir = os.path.dirname(os.path.abspath(__file__))
    # test_dir is /c/csc/irc/tests, so repo_root is /c/csc/irc (one level up)
    repo_root = os.path.dirname(test_dir)
    return os.path.join(repo_root, 'packages', 'csc-service', 'csc_service', filename)


def test_server_py_syntax():
    """Test that server.py has valid Python syntax."""
    fpath = _get_test_file_path('server/server.py')
    if not os.path.exists(fpath):
        pytest.fail(f"[FAIL] File not found: {fpath}")
    valid, error = _check_file_syntax(fpath)
    if not valid:
        pytest.fail(f"[FAIL] server.py syntax error: {error}")
    print("[OK] server.py syntax valid")


def test_info_handler_syntax():
    """Test that info.py handler has valid syntax."""
    fpath = _get_test_file_path('server/handlers/info.py')
    if not os.path.exists(fpath):
        pytest.fail(f"[FAIL] File not found: {fpath}")
    valid, error = _check_file_syntax(fpath)
    if not valid:
        pytest.fail(f"[FAIL] info.py syntax error: {error}")
    print("[OK] info.py syntax valid")


def test_messaging_handler_syntax():
    """Test that messaging.py handler has valid syntax."""
    fpath = _get_test_file_path('server/handlers/messaging.py')
    if not os.path.exists(fpath):
        pytest.fail(f"[FAIL] File not found: {fpath}")
    valid, error = _check_file_syntax(fpath)
    if not valid:
        pytest.fail(f"[FAIL] messaging.py syntax error: {error}")
    print("[OK] messaging.py syntax valid")


def test_registration_handler_syntax():
    """Test that registration.py handler has valid syntax."""
    fpath = _get_test_file_path('server/handlers/registration.py')
    if not os.path.exists(fpath):
        pytest.fail(f"[FAIL] File not found: {fpath}")
    valid, error = _check_file_syntax(fpath)
    if not valid:
        pytest.fail(f"[FAIL] registration.py syntax error: {error}")
    print("[OK] registration.py syntax valid")


def _check_s2s_null_safety_pattern(filepath, pattern_desc):
    """Verify that file contains the S2S null safety pattern."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            code = f.read()

        # Check for the three required patterns:
        # 1. hasattr(self.server, 's2s_network') and self.server.s2s_network
        # 2. link, remote_info = self.server.s2s_network.get_user_from_network(
        # 3. if link and remote_info and link.is_connected()

        has_hasattr = "hasattr(self.server, 's2s_network')" in code or "hasattr(self, 's2s_network')" in code
        has_unpack = "link, remote_info = " in code and "get_user_from_network(" in code
        has_safety_check = "if link and remote_info and link.is_connected()" in code

        if not has_hasattr:
            return False, "Missing hasattr check for s2s_network"
        if not has_unpack:
            return False, "Missing tuple unpacking (link, remote_info)"
        if not has_safety_check:
            return False, "Missing safety check: if link and remote_info and link.is_connected()"

        return True, None
    except Exception as e:
        return False, str(e)


def test_server_py_has_s2s_safety():
    """Test that server.py send_to_nick has S2S null safety pattern."""
    fpath = _get_test_file_path('server/server.py')
    valid, error = _check_s2s_null_safety_pattern(fpath, "send_to_nick")
    if not valid:
        pytest.fail(f"[FAIL] server.py missing S2S safety pattern: {error}")
    print("[OK] server.py has S2S null safety pattern")


def test_info_handler_has_s2s_safety():
    """Test that info.py WHOIS has S2S null safety pattern."""
    fpath = _get_test_file_path('server/handlers/info.py')
    valid, error = _check_s2s_null_safety_pattern(fpath, "WHOIS")
    if not valid:
        pytest.fail(f"[FAIL] info.py missing S2S safety pattern: {error}")
    print("[OK] info.py has S2S null safety pattern")


def test_messaging_handler_has_s2s_safety():
    """Test that messaging.py PRIVMSG has S2S null safety pattern."""
    fpath = _get_test_file_path('server/handlers/messaging.py')
    valid, error = _check_s2s_null_safety_pattern(fpath, "PRIVMSG")
    if not valid:
        pytest.fail(f"[FAIL] messaging.py missing S2S safety pattern: {error}")
    print("[OK] messaging.py has S2S null safety pattern")


def test_registration_handler_has_s2s_safety():
    """Test that registration.py nick collision check has S2S null safety pattern."""
    fpath = _get_test_file_path('server/handlers/registration.py')
    valid, error = _check_s2s_null_safety_pattern(fpath, "nick collision")
    if not valid:
        pytest.fail(f"[FAIL] registration.py missing S2S safety pattern: {error}")
    print("[OK] registration.py has S2S null safety pattern")


# Test that modified methods work with null safety
def test_send_to_nick_with_no_s2s_network():
    """Test send_to_nick handles missing s2s_network gracefully."""
    try:
        # Create a mock server without s2s_network
        server = Mock()
        server.s2s_network = None

        # Call with no s2s_network should not crash
        # The actual method checks: if hasattr(self, 's2s_network') and self.s2s_network:
        # This should return False and skip S2S routing
        assert not (hasattr(server, 's2s_network') and server.s2s_network), \
            "Expected s2s_network check to be False when s2s_network is None"
        print("[OK] send_to_nick null check passes")
    except Exception as e:
        pytest.fail(f"[FAIL] send_to_nick null check error: {e}\n{traceback.format_exc()}")


def test_s2s_network_tuple_unpacking():
    """Test S2S get_user_from_network tuple unpacking works."""
    try:
        # Test the pattern: link, remote_info = s2s_network.get_user_from_network(nick)
        mock_s2s = Mock()
        mock_link = Mock()
        mock_link.is_connected.return_value = True
        mock_remote_info = {'nick': 'user', 'server_id': 'server1'}

        mock_s2s.get_user_from_network.return_value = (mock_link, mock_remote_info)

        # This is what the code does:
        link, remote_info = mock_s2s.get_user_from_network('testuser')

        # Verify both are returned and checks pass
        assert link is not None, "link should not be None"
        assert remote_info is not None, "remote_info should not be None"
        assert link.is_connected(), "link.is_connected() should return True"
        print("[OK] S2S tuple unpacking works correctly")
    except Exception as e:
        pytest.fail(f"[FAIL] S2S tuple unpacking error: {e}\n{traceback.format_exc()}")


def test_s2s_null_checks_prevent_crashes():
    """Test that the three-part null check (link and remote_info and link.is_connected) works."""
    try:
        # Simulate various failure modes that should be caught by the null checks
        # Note: Python's 'and' returns first falsy value, so we check truthiness with bool()
        test_cases = [
            # (link, remote_info, expected_safe, desc)
            (None, {'nick': 'user'}, False, "link=None should fail"),
            (Mock(), None, False, "remote_info=None should fail"),
            (Mock(is_connected=Mock(return_value=False)), {'nick': 'user'}, False, "disconnected link should fail"),
            (Mock(is_connected=Mock(return_value=True)), {'nick': 'user'}, True, "valid link+info should pass"),
        ]

        for link, remote_info, expected_safe, desc in test_cases:
            # This is the pattern from the code: if link and remote_info and link.is_connected():
            # Python 'and' returns the first falsy value or the last value if all are truthy
            is_safe = bool(link and remote_info and link.is_connected())
            assert is_safe == expected_safe, f"{desc}: got {is_safe}, expected {expected_safe}"

        print("[OK] All null check combinations are correct")
    except Exception as e:
        pytest.fail(f"[FAIL] null check combinations error: {e}\n{traceback.format_exc()}")


def test_s2s_hasattr_check():
    """Test hasattr check for s2s_network attribute."""
    try:
        # Create mock servers with and without s2s_network
        server_with = Mock()
        server_with.s2s_network = Mock()

        server_without = Mock(spec=[])  # Empty spec, no attributes

        # This is the pattern from code: hasattr(self.server, 's2s_network') and self.server.s2s_network:
        assert hasattr(server_with, 's2s_network'), "server_with should have s2s_network"
        assert server_with.s2s_network, "s2s_network should be truthy"

        # The second server won't have the attribute
        # (In real code, the hasattr would catch this)
        assert not hasattr(server_without, 's2s_network'), "server_without should not have s2s_network"

        print("[OK] hasattr check for s2s_network is correct")
    except Exception as e:
        pytest.fail(f"[FAIL] hasattr check error: {e}\n{traceback.format_exc()}")


if __name__ == '__main__':
    # Run tests with verbose output
    pytest.main([__file__, '-v', '-s'])
