import time
import pytest
from csc_ai_api.context import ContextManager
from csc_ai_api.standoff import StandoffManager
from csc_ai_api.ignore import IgnoreManager
from csc_ai_api.focus import FocusManager
from csc_ai_api.perform import PerformManager
from pathlib import Path

def test_context_manager_backscroll():
    cm = ContextManager(backscroll=3)
    cm.buffer("#test", "user1", "msg1")
    cm.buffer("#test", "user2", "msg2")
    cm.buffer("#test", "user3", "msg3")
    cm.buffer("#test", "user4", "msg4")
    
    ctx = cm.get("#test")
    assert len(ctx) == 3
    assert ctx == ["user2: msg2", "user3: msg3", "user4: msg4"]

def test_context_manager_mention():
    cm = ContextManager()
    wakewords = ["@bot", "bot:"]
    assert cm.is_direct_mention("hello @bot how are you", wakewords) is True
    assert cm.is_direct_mention("Bot: are you there?", wakewords) is True
    assert cm.is_direct_mention("just a message", wakewords) is False

def test_ignore_manager():
    im = IgnoreManager(timeout_secs=1)
    im.parse("!ignore bot", "bot")
    assert im.is_ignored() is True
    
    im.parse("!ignore other", "bot")
    im.clear() # Reset for test
    im.parse("!ignore other", "bot")
    assert im.is_ignored() is False
    
    im.parse("!ignore", "bot")
    assert im.is_ignored() is True
    time.sleep(1.1)
    assert im.is_ignored() is False

def test_focus_manager():
    fm = FocusManager(window_secs=1)
    assert fm.is_focused("#dev") is False
    fm.mark_responded("#dev")
    assert fm.is_focused("#dev") is True
    time.sleep(1.1)
    assert fm.is_focused("#dev") is False

def test_standoff_manager_coalescing():
    sm = StandoffManager()
    called = []
    
    def callback(channel, messages):
        called.append((channel, messages))
        
    sm.add("#chan", "user1", "hello")
    sm.start_or_reset("#chan", 200, callback)
    
    time.sleep(0.1)
    sm.add("#chan", "user2", "world")
    sm.start_or_reset("#chan", 200, callback)
    
    # Wait for timer (should fire at T=0.1 + 0.2 = 0.3)
    time.sleep(0.5)
    
    assert len(called) == 1
    assert called[0][0] == "#chan"
    assert len(called[0][1]) == 2
    assert called[0][1] == [("user1", "hello"), ("user2", "world")]

def test_perform_manager_vars(tmp_path):
    conf = tmp_path / "client.conf"
    conf.write_text("[identity]\nnick=testbot\nchannels=#dev\n[perform]\ntest=JOIN $channels\n")
    
    pm = PerformManager(conf)
    pm.load()
    
    results = []
    def collector(line):
        results.append(line)
        
    pm.fire("test", send_fn=collector)
    assert results == ["JOIN #dev"]
    assert pm.nick == "testbot"
    assert pm.channels == ["#dev"]

def test_standoff_cancelled_on_mention():
    """When a direct mention arrives, any pending standoff timer must be
    cancelled so the coalesced response does not fire after the immediate
    mention response."""
    sm = StandoffManager()
    fired = []

    def callback(channel, messages):
        fired.append((channel, messages))

    # Simulate chatter that starts a coalesce timer
    sm.add("#dev", "alice", "hey everyone")
    sm.start_or_reset("#dev", 300, callback)

    # Mention arrives -- caller should cancel the timer
    sm.cancel("#dev")

    # Wait past the original timer window
    time.sleep(0.5)

    # Timer must NOT have fired
    assert fired == [], "standoff timer fired after cancel (mention path)"

    # Buffer should still hold the pre-mention message (cancel does not flush)
    remaining = sm.flush("#dev")
    assert remaining == [("alice", "hey everyone")]


def test_codex_client_instantiation(tmp_path):
    # Setup a dummy client.conf
    agent_dir = tmp_path / "codex"
    agent_dir.mkdir()
    conf = agent_dir / "client.conf"
    conf.write_text("[identity]\nnick=codex\nserver=127.0.0.1\n")
    
    from csc_codex import CodexClient
    import os
    # Set dummy key to avoid ValueError during init if needed
    os.environ["OPENAI_API_KEY"] = "sk-test"
    
    client = CodexClient(config_path=str(conf))
    assert client.name == "codex"
    assert hasattr(client, "respond")

def test_claude_client_instantiation(tmp_path):
    agent_dir = tmp_path / "claude"
    agent_dir.mkdir()
    conf = agent_dir / "client.conf"
    conf.write_text("[identity]\nnick=claude\nserver=127.0.0.1\n")
    
    from csc_claude import ClaudeClient
    import os
    os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test"
    
    client = ClaudeClient(config_path=str(conf))
    assert client.name == "claude"
    assert hasattr(client, "respond")
