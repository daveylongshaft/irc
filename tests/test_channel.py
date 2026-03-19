"""Comprehensive tests for Channel and ChannelManager classes.

Tests cover:
- Channel creation and initialization
- Member management (add, remove, lookup)
- Member modes (op, voice checks)
- Display nick and names list
- Permission checks (can_speak, can_set_topic)
- Ban and invite list (direct set manipulation)
- ChannelManager operations (ensure, get, remove, list, find, nick removal)
- Thread safety and edge cases
"""

import pytest
from unittest.mock import patch
from csc_service.shared.channel import Channel, ChannelManager, _nk


# ============================================================================
# Helper: _nk nick normaliser
# ============================================================================

class TestNkHelper:
    """Test the _nk() nick normalisation function."""

    def test_nk_lowercase(self):
        assert _nk('Alice') == 'alice'
        assert _nk('BOB') == 'bob'
        assert _nk('charlie') == 'charlie'

    def test_nk_empty_string(self):
        assert _nk('') == ''

    def test_nk_none(self):
        assert _nk(None) == ''


# ============================================================================
# Channel: basics
# ============================================================================

class TestChannelBasics:
    """Test basic Channel initialization and properties."""

    def test_channel_creation(self):
        """New channel has correct defaults."""
        ch = Channel('#test')
        assert ch.name == '#test'
        assert ch.topic == ''
        assert len(ch.members) == 0
        assert len(ch.modes) == 0
        assert isinstance(ch.mode_params, dict) and len(ch.mode_params) == 0
        assert len(ch.ban_list) == 0
        assert len(ch.invite_list) == 0
        assert ch.created > 0

    def test_channel_preserves_name_case(self):
        ch = Channel('#TestChannel')
        assert ch.name == '#TestChannel'

    @patch('csc_service.shared.channel.time')
    def test_channel_creation_timestamp(self, mock_time_mod):
        mock_time_mod.time.return_value = 1234567890.0
        ch = Channel('#test')
        assert ch.created == 1234567890.0


# ============================================================================
# Channel: member management
# ============================================================================

class TestChannelMembers:
    """Test add_member, remove_member, has_member, get_member."""

    def test_add_member(self):
        ch = Channel('#test')
        ch.add_member('alice', ('127.0.0.1', 12345))
        assert ch.has_member('alice')
        assert ch.member_count() == 1

    def test_add_member_case_insensitive_lookup(self):
        ch = Channel('#test')
        ch.add_member('Alice', ('127.0.0.1', 12345))
        assert ch.has_member('alice')
        assert ch.has_member('ALICE')
        assert ch.has_member('Alice')

    def test_add_member_preserves_display_nick(self):
        ch = Channel('#test')
        ch.add_member('AlIcE', ('127.0.0.1', 12345))
        member = ch.get_member('alice')
        assert member is not None
        assert member['nick'] == 'AlIcE'

    def test_add_member_with_modes(self):
        ch = Channel('#test')
        ch.add_member('alice', ('127.0.0.1', 12345), modes={'o', 'v'})
        member = ch.get_member('alice')
        assert 'o' in member['modes']
        assert 'v' in member['modes']

    def test_add_member_default_empty_modes(self):
        ch = Channel('#test')
        ch.add_member('alice', ('127.0.0.1', 12345))
        member = ch.get_member('alice')
        assert member['modes'] == set() or len(member['modes']) == 0

    def test_remove_member(self):
        ch = Channel('#test')
        ch.add_member('alice', ('127.0.0.1', 12345))
        ch.remove_member('alice')
        assert not ch.has_member('alice')

    def test_remove_member_case_insensitive(self):
        ch = Channel('#test')
        ch.add_member('Alice', ('127.0.0.1', 12345))
        ch.remove_member('ALICE')
        assert not ch.has_member('alice')

    def test_remove_nonexistent_member(self):
        """Removing a non-existent member should not raise."""
        ch = Channel('#test')
        ch.remove_member('nonexistent')  # should not raise

    def test_get_member_returns_none_for_missing(self):
        ch = Channel('#test')
        assert ch.get_member('nonexistent') is None

    def test_has_member_false_for_empty_channel(self):
        ch = Channel('#test')
        assert not ch.has_member('alice')

    def test_multiple_members(self):
        ch = Channel('#test')
        ch.add_member('alice', ('127.0.0.1', 1001))
        ch.add_member('bob', ('127.0.0.1', 1002))
        ch.add_member('charlie', ('127.0.0.1', 1003))
        assert ch.member_count() == 3
        assert ch.has_member('alice')
        assert ch.has_member('bob')
        assert ch.has_member('charlie')

    def test_add_member_replaces_existing(self):
        """Re-adding overwrites the previous entry."""
        ch = Channel('#test')
        ch.add_member('alice', ('127.0.0.1', 1001))
        ch.add_member('alice', ('127.0.0.1', 9999), modes={'o'})
        assert ch.member_count() == 1
        member = ch.get_member('alice')
        assert member['addr'] == ('127.0.0.1', 9999)
        assert 'o' in member['modes']


# ============================================================================
# Channel: display nick & names list
# ============================================================================

class TestDisplayNickAndNames:
    """Test get_display_nick and get_names_list."""

    def test_get_display_nick_preserves_case(self):
        ch = Channel('#test')
        ch.add_member('AlIcE', ('127.0.0.1', 1001))
        assert ch.get_display_nick('alice') == 'AlIcE'

    def test_get_display_nick_returns_input_if_not_member(self):
        ch = Channel('#test')
        assert ch.get_display_nick('NoSuchUser') == 'NoSuchUser'

    def test_names_list_op_prefix(self):
        ch = Channel('#test')
        ch.add_member('alice', ('127.0.0.1', 1001), modes={'o'})
        names = ch.get_names_list()
        assert '@alice' in names

    def test_names_list_voice_prefix(self):
        ch = Channel('#test')
        ch.add_member('bob', ('127.0.0.1', 1002), modes={'v'})
        names = ch.get_names_list()
        assert '+bob' in names

    def test_names_list_no_prefix(self):
        ch = Channel('#test')
        ch.add_member('charlie', ('127.0.0.1', 1003))
        names = ch.get_names_list()
        assert 'charlie' in names
        assert '@charlie' not in names
        assert '+charlie' not in names

    def test_names_list_sorted(self):
        ch = Channel('#test')
        ch.add_member('zara', ('127.0.0.1', 1001))
        ch.add_member('alice', ('127.0.0.1', 1002))
        names = ch.get_names_list()
        parts = names.split()
        assert parts == sorted(parts)

    def test_names_list_empty_channel(self):
        ch = Channel('#test')
        assert ch.get_names_list() == ''


# ============================================================================
# Channel: member mode queries (is_op, has_voice)
# ============================================================================

class TestMemberModeQueries:
    """Test is_op, has_voice helper methods."""

    def test_is_op_true(self):
        ch = Channel('#test')
        ch.add_member('alice', ('127.0.0.1', 1001), modes={'o'})
        assert ch.is_op('alice') is True

    def test_is_op_false_no_mode(self):
        ch = Channel('#test')
        ch.add_member('bob', ('127.0.0.1', 1002))
        assert ch.is_op('bob') is False

    def test_is_op_false_not_member(self):
        ch = Channel('#test')
        assert ch.is_op('nonexistent') is False

    def test_is_op_case_insensitive(self):
        ch = Channel('#test')
        ch.add_member('Alice', ('127.0.0.1', 1001), modes={'o'})
        assert ch.is_op('ALICE') is True

    def test_has_voice_true(self):
        ch = Channel('#test')
        ch.add_member('alice', ('127.0.0.1', 1001), modes={'v'})
        assert ch.has_voice('alice') is True

    def test_has_voice_false_no_mode(self):
        ch = Channel('#test')
        ch.add_member('bob', ('127.0.0.1', 1002))
        assert ch.has_voice('bob') is False

    def test_has_voice_false_not_member(self):
        ch = Channel('#test')
        assert ch.has_voice('nonexistent') is False


# ============================================================================
# Channel: permission checks (can_speak, can_set_topic)
# ============================================================================

class TestPermissionChecks:
    """Test can_speak and can_set_topic."""

    # -- can_speak --

    def test_can_speak_unmoderated(self):
        """Anyone can speak in an unmoderated channel."""
        ch = Channel('#test')
        ch.add_member('alice', ('127.0.0.1', 1001))
        assert ch.can_speak('alice') is True

    def test_can_speak_moderated_op(self):
        ch = Channel('#test')
        ch.modes.add('m')
        ch.add_member('alice', ('127.0.0.1', 1001), modes={'o'})
        assert ch.can_speak('alice') is True

    def test_can_speak_moderated_voice(self):
        ch = Channel('#test')
        ch.modes.add('m')
        ch.add_member('alice', ('127.0.0.1', 1001), modes={'v'})
        assert ch.can_speak('alice') is True

    def test_cannot_speak_moderated_regular(self):
        ch = Channel('#test')
        ch.modes.add('m')
        ch.add_member('alice', ('127.0.0.1', 1001))
        assert ch.can_speak('alice') is False

    def test_cannot_speak_moderated_nonmember(self):
        ch = Channel('#test')
        ch.modes.add('m')
        assert ch.can_speak('outsider') is False

    # -- can_set_topic --

    def test_can_set_topic_unrestricted(self):
        """Without +t anyone can set topic."""
        ch = Channel('#test')
        ch.add_member('alice', ('127.0.0.1', 1001))
        assert ch.can_set_topic('alice') is True

    def test_can_set_topic_restricted_op(self):
        ch = Channel('#test')
        ch.modes.add('t')
        ch.add_member('alice', ('127.0.0.1', 1001), modes={'o'})
        assert ch.can_set_topic('alice') is True

    def test_cannot_set_topic_restricted_regular(self):
        ch = Channel('#test')
        ch.modes.add('t')
        ch.add_member('alice', ('127.0.0.1', 1001))
        assert ch.can_set_topic('alice') is False


# ============================================================================
# Channel: modes / mode_params (direct attribute manipulation)
# ============================================================================

class TestChannelModes:
    """Test channel modes via direct set manipulation (matching actual API)."""

    def test_add_mode(self):
        ch = Channel('#test')
        ch.modes.add('n')
        assert 'n' in ch.modes

    def test_remove_mode(self):
        ch = Channel('#test')
        ch.modes.add('n')
        ch.modes.discard('n')
        assert 'n' not in ch.modes

    def test_mode_params_key(self):
        ch = Channel('#test')
        ch.modes.add('k')
        ch.mode_params['k'] = 'secret'
        assert ch.mode_params['k'] == 'secret'

    def test_mode_params_limit(self):
        ch = Channel('#test')
        ch.modes.add('l')
        ch.mode_params['l'] = 50
        assert ch.mode_params['l'] == 50

    def test_remove_mode_with_param(self):
        ch = Channel('#test')
        ch.modes.add('k')
        ch.mode_params['k'] = 'secret'
        ch.modes.discard('k')
        ch.mode_params.pop('k', None)
        assert 'k' not in ch.modes
        assert 'k' not in ch.mode_params


# ============================================================================
# Channel: topic (direct attribute)
# ============================================================================

class TestTopicManagement:
    """Test topic via direct attribute access."""

    def test_topic_default_empty(self):
        ch = Channel('#test')
        assert ch.topic == ''

    def test_set_topic(self):
        ch = Channel('#test')
        ch.topic = 'Welcome!'
        assert ch.topic == 'Welcome!'

    def test_clear_topic(self):
        ch = Channel('#test')
        ch.topic = 'old'
        ch.topic = ''
        assert ch.topic == ''


# ============================================================================
# Channel: ban_list / invite_list (direct set manipulation)
# ============================================================================

class TestBanAndInviteLists:
    """Test ban_list and invite_list as raw sets."""

    def test_add_ban(self):
        ch = Channel('#test')
        ch.ban_list.add('*!*@badhost.com')
        assert '*!*@badhost.com' in ch.ban_list

    def test_remove_ban(self):
        ch = Channel('#test')
        ch.ban_list.add('*!*@badhost.com')
        ch.ban_list.discard('*!*@badhost.com')
        assert '*!*@badhost.com' not in ch.ban_list

    def test_add_invite(self):
        ch = Channel('#test')
        ch.invite_list.add('alice')
        assert 'alice' in ch.invite_list

    def test_invite_stored_lowercase(self):
        ch = Channel('#test')
        ch.invite_list.add(_nk('Alice'))
        assert 'alice' in ch.invite_list

    def test_remove_invite(self):
        ch = Channel('#test')
        ch.invite_list.add('alice')
        ch.invite_list.discard('alice')
        assert 'alice' not in ch.invite_list


# ============================================================================
# Channel: member_count
# ============================================================================

class TestMemberCount:
    def test_member_count_empty(self):
        ch = Channel('#test')
        assert ch.member_count() == 0

    def test_member_count_after_add(self):
        ch = Channel('#test')
        ch.add_member('alice', ('127.0.0.1', 1001))
        ch.add_member('bob', ('127.0.0.1', 1002))
        assert ch.member_count() == 2

    def test_member_count_after_remove(self):
        ch = Channel('#test')
        ch.add_member('alice', ('127.0.0.1', 1001))
        ch.add_member('bob', ('127.0.0.1', 1002))
        ch.remove_member('alice')
        assert ch.member_count() == 1


# ============================================================================
# ChannelManager
# ============================================================================

class TestChannelManager:
    """Test ChannelManager functionality."""

    def test_manager_creation_has_default_channel(self):
        mgr = ChannelManager()
        assert mgr.get_channel('#general') is not None

    def test_ensure_channel_creates(self):
        mgr = ChannelManager()
        ch = mgr.ensure_channel('#test')
        assert ch is not None
        assert ch.name == '#test'
        assert mgr.get_channel('#test') is ch

    def test_ensure_channel_returns_existing(self):
        mgr = ChannelManager()
        ch1 = mgr.ensure_channel('#test')
        ch2 = mgr.ensure_channel('#test')
        assert ch1 is ch2

    def test_ensure_channel_case_insensitive(self):
        mgr = ChannelManager()
        ch1 = mgr.ensure_channel('#Test')
        ch2 = mgr.ensure_channel('#test')
        assert ch1 is ch2

    def test_get_nonexistent_channel(self):
        mgr = ChannelManager()
        assert mgr.get_channel('#nosuch') is None

    def test_get_channel_case_insensitive(self):
        mgr = ChannelManager()
        mgr.ensure_channel('#Foo')
        assert mgr.get_channel('#foo') is not None

    def test_remove_channel(self):
        mgr = ChannelManager()
        mgr.ensure_channel('#test')
        result = mgr.remove_channel('#test')
        assert result is True
        assert mgr.get_channel('#test') is None

    def test_remove_nonexistent_channel(self):
        mgr = ChannelManager()
        result = mgr.remove_channel('#nosuch')
        assert result is False

    def test_cannot_remove_default_channel(self):
        mgr = ChannelManager()
        result = mgr.remove_channel('#general')
        assert result is False
        assert mgr.get_channel('#general') is not None

    def test_list_channels_includes_default(self):
        mgr = ChannelManager()
        channels = mgr.list_channels()
        names = [ch.name.lower() for ch in channels]
        assert '#general' in names

    def test_list_channels_after_adding(self):
        mgr = ChannelManager()
        mgr.ensure_channel('#test1')
        mgr.ensure_channel('#test2')
        channels = mgr.list_channels()
        # #general + #test1 + #test2 = 3
        assert len(channels) == 3

    def test_find_channels_for_nick(self):
        mgr = ChannelManager()
        ch1 = mgr.ensure_channel('#a')
        ch2 = mgr.ensure_channel('#b')
        ch1.add_member('alice', ('127.0.0.1', 1001))
        ch2.add_member('alice', ('127.0.0.1', 1001))
        found = mgr.find_channels_for_nick('alice')
        assert len(found) == 2

    def test_find_channels_for_nick_case_insensitive(self):
        mgr = ChannelManager()
        ch = mgr.ensure_channel('#a')
        ch.add_member('Alice', ('127.0.0.1', 1001))
        found = mgr.find_channels_for_nick('ALICE')
        assert len(found) == 1

    def test_find_channels_for_nick_not_found(self):
        mgr = ChannelManager()
        found = mgr.find_channels_for_nick('nobody')
        assert found == []

    def test_remove_nick_from_all(self):
        mgr = ChannelManager()
        ch1 = mgr.ensure_channel('#a')
        ch2 = mgr.ensure_channel('#b')
        ch1.add_member('alice', ('127.0.0.1', 1001))
        ch2.add_member('alice', ('127.0.0.1', 1001))
        removed = mgr.remove_nick_from_all('alice')
        assert len(removed) == 2
        assert not ch1.has_member('alice')

    def test_remove_nick_from_all_cleans_empty_non_default(self):
        """Empty non-default channels are cleaned up after nick removal."""
        mgr = ChannelManager()
        ch = mgr.ensure_channel('#temp')
        ch.add_member('alice', ('127.0.0.1', 1001))
        mgr.remove_nick_from_all('alice')
        # #temp was the only member; should be removed
        assert mgr.get_channel('#temp') is None

    def test_remove_nick_from_all_keeps_default(self):
        """Default channel is kept even if it becomes empty."""
        mgr = ChannelManager()
        default_ch = mgr.get_channel('#general')
        default_ch.add_member('alice', ('127.0.0.1', 1001))
        mgr.remove_nick_from_all('alice')
        assert mgr.get_channel('#general') is not None


# ============================================================================
# Edge cases
# ============================================================================

class TestEdgeCases:
    """Miscellaneous edge-case tests."""

    def test_channel_with_no_hash(self):
        """Channel without '#' prefix still works (no validation)."""
        ch = Channel('nohash')
        assert ch.name == 'nohash'

    def test_empty_nick_member_operations(self):
        ch = Channel('#test')
        ch.add_member('', ('127.0.0.1', 1001))
        assert ch.has_member('')
        ch.remove_member('')
        assert not ch.has_member('')

    def test_member_count_matches_len(self):
        ch = Channel('#test')
        ch.add_member('a', ('127.0.0.1', 1001))
        ch.add_member('b', ('127.0.0.1', 1002))
        assert ch.member_count() == len(ch.members)
