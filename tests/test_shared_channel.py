```python
import pytest
from unittest.mock import Mock, MagicMock, patch
import sys
import os

# Mock the csc_shared module before importing
sys.modules['csc_shared'] = MagicMock()
sys.modules['csc_shared.data'] = MagicMock()
sys.modules['csc_shared.log'] = MagicMock()
sys.modules['csc_shared.platform'] = MagicMock()

from csc_shared.channel import Channel, ChannelManager


class TestChannel:
    """Test suite for the Channel class."""

    def setup_method(self):
        """Set up a fresh Channel instance for each test."""
        self.channel = Channel("#test")
        self.addr1 = ("127.0.0.1", 10001)
        self.addr2 = ("127.0.0.1", 10002)
        self.addr3 = ("127.0.0.1", 10003)

    def test_add_member(self):
        """Test that add_member adds a nick to the channel."""
        self.channel.add_member("alice", self.addr1)
        assert self.channel.has_member("alice")

    def test_remove_member(self):
        """Test that remove_member removes a nick from the channel."""
        self.channel.add_member("alice", self.addr1)
        self.channel.remove_member("alice")
        assert not self.channel.has_member("alice")

    def test_remove_member_nonexistent(self):
        """Test that remove_member on a missing nick does not raise."""
        self.channel.remove_member("ghost")  # should not raise

    def test_has_member_false(self):
        """Test that has_member returns False for non-members."""
        assert not self.channel.has_member("nobody")

    def test_member_count(self):
        """Test that member_count returns the correct count."""
        assert self.channel.member_count() == 0
        self.channel.add_member("alice", self.addr1)
        assert self.channel.member_count() == 1
        self.channel.add_member("bob", self.addr2)
        assert self.channel.member_count() == 2
        self.channel.remove_member("alice")
        assert self.channel.member_count() == 1

    def test_get_names_list_no_ops(self):
        """Test get_names_list with no operators returns sorted nicks."""
        self.channel.add_member("charlie", self.addr3)
        self.channel.add_member("alice", self.addr1)
        self.channel.add_member("bob", self.addr2)
        names = self.channel.get_names_list()
        assert names == "alice bob charlie"

    def test_get_names_list_with_ops(self):
        """Test get_names_list prefixes ops with @."""
        self.channel.add_member("alice", self.addr1, modes={"o"})
        self.channel.add_member("bob", self.addr2)
        names = self.channel.get_names_list()
        assert names == "@alice bob"

    def test_get_names_list_empty(self):
        """Test get_names_list with no members returns empty string."""
        names = self.channel.get_names_list()
        assert names == ""

    def test_is_op_true(self):
        """Test is_op returns True for a channel operator."""
        self.channel.add_member("alice", self.addr1, modes={"o"})
        assert self.channel.is_op("alice")

    def test_is_op_false_regular_member(self):
        """Test is_op returns False for a regular member."""
        self.channel.add_member("bob", self.addr2)
        assert not self.channel.is_op("bob")

    def test_is_op_false_nonmember(self):
        """Test is_op returns False for a non-member."""
        assert not self.channel.is_op("ghost")

    def test_topic_default_empty(self):
        """Test that a new channel has an empty topic."""
        assert self.channel.topic == ""

    def test_topic_setting(self):
        """Test setting the channel topic."""
        self.channel.topic = "Welcome to #test"
        assert self.channel.topic == "Welcome to #test"

    def test_channel_name(self):
        """Test that the channel name is set correctly."""
        assert self.channel.name == "#test"

    def test_created_timestamp(self):
        """Test that the created timestamp is a positive number."""
        assert self.channel.created > 0

    def test_add_member_with_default_modes(self):
        """Test adding a member with default (empty) modes."""
        self.channel.add_member("dave", self.addr1)
        assert self.channel.has_member("dave")
        assert not self.channel.is_op("dave")

    def test_add_member_multiple_modes(self):
        """Test adding a member with multiple modes."""
        self.channel.add_member("eve", self.addr2, modes={"o", "v"})
        assert self.channel.has_member("eve")
        assert self.channel.is_op("eve")

    def test_get_names_list_with_multiple_ops(self):
        """Test get_names_list with multiple operators."""
        self.channel.add_member("alice", self.addr1, modes={"o"})
        self.channel.add_member("bob", self.addr2, modes={"o"})
        self.channel.add_member("charlie", self.addr3)
        names = self.channel.get_names_list()
        assert "@alice" in names
        assert "@bob" in names
        assert "charlie" in names


class TestChannelManager:
    """Test suite for the ChannelManager class."""

    def setup_method(self):
        """Set up a fresh ChannelManager for each test."""
        self.manager = ChannelManager()
        self.addr1 = ("127.0.0.1", 10001)
        self.addr2 = ("127.0.0.1", 10002)

    def test_default_general_exists(self):
        """Test that #general is created by default on init."""
        ch = self.manager.get_channel("#general")
        assert ch is not None
        assert ch.name == "#general"

    def test_ensure_channel_creates_new(self):
        """Test that ensure_channel creates a new channel if it doesn't exist."""
        ch = self.manager.ensure_channel("#new")
        assert ch is not None
        assert ch.name == "#new"

    def test_ensure_channel_returns_existing(self):
        """Test that ensure_channel returns the same channel object on repeated calls."""
        ch1 = self.manager.ensure_channel("#test")
        ch2 = self.manager.ensure_channel("#test")
        assert ch1 is ch2

    def test_get_channel_returns_none_for_missing(self):
        """Test that get_channel returns None when channel does not exist."""
        assert self.manager.get_channel("#nonexistent") is None

    def test_remove_channel(self):
        """Test that remove_channel removes a non-default channel."""
        self.manager.ensure_channel("#temp")
        result = self.manager.remove_channel("#temp")
        assert result is True
        assert self.manager.get_channel("#temp") is None

    def test_remove_channel_nonexistent(self):
        """Test that remove_channel returns False for a channel that doesn't exist."""
        result = self.manager.remove_channel("#ghost")
        assert result is False

    def test_remove_channel_default_general(self):
        """Test that remove_channel returns False when trying to remove #general."""
        result = self.manager.remove_channel("#general")
        assert result is False

    def test_list_channels(self):
        """Test that list_channels returns all existing channels."""
        self.manager.ensure_channel("#channel1")
        self.manager.ensure_channel("#channel2")
        channels = self.manager.list_channels()
        channel_names = [ch.name for ch in channels]
        assert "#general" in channel_names
        assert "#channel1" in channel_names
        assert "#channel2" in channel_names

    def test_list_channels_empty_except_general(self):
        """Test list_channels when only #general exists."""
        manager = ChannelManager()
        channels = manager.list_channels()
        assert len(channels) == 1
        assert channels[0].name == "#general"

    def test_channel_isolation(self):
        """Test that members in one channel don't appear in another."""
        ch1 = self.manager.ensure_channel("#channel1")
        ch2 = self.manager.ensure_channel("#channel2")
        ch1.add_member("alice", self.addr1)
        ch2.add_member("bob", self.addr2)
        assert ch1.has_member("alice")
        assert not ch1.has_member("bob")
        assert ch2.has_member("bob")
        assert not ch2.has_member("alice")

    def test_get_channel_general(self):
        """Test that get_channel can retrieve #general."""
        ch = self.manager.get_channel("#general")
        assert ch is not None
        assert ch.name == "#general"

    def test_ensure_channel_preserves_existing_members(self):
        """Test that ensure_channel on an existing channel preserves members."""
        ch1 = self.manager.ensure_channel("#persist")
        ch1.add_member("alice", self.addr1)
        ch2 = self.manager.ensure_channel("#persist")
        assert ch2.has_member("alice")

    def test_multiple_channels_independent_topics(self):
        """Test that topics are independent between channels."""
        ch1 = self.manager.ensure_channel("#topic1")
        ch2 = self.manager.ensure_channel("#topic2")
        ch1.topic = "Topic for channel 1"
        ch2.topic = "Topic for channel 2"
        assert ch1.topic == "Topic for channel 1"
        assert ch2.topic == "Topic for channel 2"


class TestChannelIntegration:
    """Integration tests for Channel and ChannelManager."""

    def test_full_workflow(self):
        """Test a complete workflow of creating channels and managing members."""
        manager = ChannelManager()
        
        # Create channels
        ch_general = manager.get_channel("#general")
        ch_dev = manager.ensure_channel("#dev")
        
        # Add members
        addr1 = ("192.168.1.1", 5000)
        addr2 = ("192.168.1.2", 5001)
        addr3 = ("192.168.1.3", 5002)
        
        ch_general.add_member("admin", addr1, modes={"o"})
        ch_general.add_member("user1", addr2)
        
        ch_dev.add_member("dev_lead", addr1, modes={"o"})
        ch_dev.add_member("dev1", addr2)
        ch_dev.add_member("dev2", addr3)
        
        # Verify state
        assert ch_general.member_count() == 2
        assert ch_dev.member_count() == 3
        
        assert ch_general.is_op("admin")
        assert not ch_general.is_op("user1")
        
        assert ch_dev.is_op("dev_lead")
        assert not ch_dev.is_op("dev1")
        
        # Remove member
        ch_dev.remove_member("dev1")
        assert ch_dev.member_count() == 2
        assert not ch_dev.has_member("dev1")
        
        # Set topics
        ch_general.topic = "General discussion"
        ch_dev.topic = "Development chat"
        
        assert ch_general.topic == "General discussion"
        assert ch_dev.topic == "Development chat"
        
        # List channels
        all_channels = manager.list_channels()
        assert len(all_channels) == 2
```