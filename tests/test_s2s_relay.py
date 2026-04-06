"""
Integration test: S2S bidirectional relay (leaf -> hub topology).

Tests that messages sent from either end of an S2S link arrive at the other.
Uses real in-process UDP sockets and threads but no TLS certs (password auth).
No external servers required.

Run with:  pytest tests/test_s2s_relay.py -v -s
"""

import os
import sys
import socket
import threading
import time
import queue

import pytest

# Wire packages into path
_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for _pkg in ("csc-server-core", "csc-network", "csc-platform", "csc-data", "csc-log", "csc-root"):
    _p = os.path.join(_REPO, "packages", _pkg)
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)


# ---------------------------------------------------------------------------
# Minimal mock server (satisfies ServerNetwork + _handle_syncmsg expectations)
# ---------------------------------------------------------------------------

class FakeChannelManager:
    def __init__(self):
        self._channels = {}

    def get_channel(self, name):
        return self._channels.get(name.lower())

    def get_all_channels(self):
        return list(self._channels.values())

    def list_channels(self):
        return list(self._channels.values())


class FakeChatBuffer:
    def append(self, *args, **kwargs):
        pass


class FakeServer:
    def __init__(self, server_id):
        self.server_id = server_id
        self.startup_time = time.time()
        self.clients = {}
        self.channel_manager = FakeChannelManager()
        self.chat_buffer = FakeChatBuffer()
        self.s2s_network = None  # set after ServerNetwork is created
        self._received = queue.Queue()  # captures broadcast_to_channel calls

    def broadcast_to_channel(self, channel_name, message, exclude=None):
        self._received.put((channel_name, message))

    def send_to_nick(self, nick, message):
        pass

    def log(self, msg, *args, **kwargs):
        # Uncomment for debug:
        # print(f"[{self.server_id}] {msg}")
        pass

    def _log(self, msg):
        self.log(msg)

    def sync_from_disk(self):
        pass


# ---------------------------------------------------------------------------
# Helper: pick a free UDP port
# ---------------------------------------------------------------------------

def _free_udp_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ---------------------------------------------------------------------------
# Fixture: two linked ServerNetwork instances (hub + leaf, password auth)
# ---------------------------------------------------------------------------

@pytest.fixture
def linked_pair():
    """
    Returns (hub_net, leaf_net, hub_server, leaf_server).

    hub_net  listens on a free port, s2s_role='hub'
    leaf_net connects to hub, s2s_role='leaf'

    Both use password auth (no TLS).  Torn down after the test.
    """
    from csc_server_core.server_network import ServerNetwork

    hub_port = _free_udp_port()
    leaf_port = _free_udp_port()

    hub_srv = FakeServer("haven.alpha")   # lower ID
    leaf_srv = FakeServer("haven.zeta")   # higher ID

    hub_net = ServerNetwork(hub_srv)
    leaf_net = ServerNetwork(leaf_srv)

    hub_srv.s2s_network = hub_net
    leaf_srv.s2s_network = leaf_net

    # Password auth, no certs
    _PW = "testpass_s2s_relay"
    hub_net.s2s_password = _PW
    leaf_net.s2s_password = _PW

    hub_net.s2s_port = hub_port
    leaf_net.s2s_port = leaf_port

    hub_net.s2s_role = "hub"
    leaf_net.s2s_role = "leaf"

    # No auto-linker — we trigger the connect manually to avoid two
    # simultaneous outbound attempts racing against each other.
    hub_net.s2s_peers = []
    leaf_net.s2s_peers = []

    # start listeners (peer linker won't start because s2s_peers is empty)
    assert hub_net.start_listener(), "Hub listener failed to start"
    assert leaf_net.start_listener(), "Leaf listener failed to start"

    # Single controlled connect from leaf to hub
    def _link():
        leaf_net._try_link_to_peer("127.0.0.1", hub_port)

    t = threading.Thread(target=_link, daemon=True)
    t.start()

    # Wait for both sides to show a connected link (up to 10s)
    deadline = time.time() + 10
    while time.time() < deadline:
        hub_links = [l for l in hub_net._links.values() if l.is_connected()]
        leaf_links = [l for l in leaf_net._links.values() if l.is_connected()]
        if hub_links and leaf_links:
            break
        time.sleep(0.1)
    else:
        pytest.fail(
            f"S2S link did not establish within 10s. "
            f"hub._links={list(hub_net._links.keys())} "
            f"leaf._links={list(leaf_net._links.keys())}"
        )

    yield hub_net, leaf_net, hub_srv, leaf_srv

    # Teardown
    hub_net._running = False
    leaf_net._running = False
    if hub_net._listener_sock:
        hub_net._listener_sock.close()
    if leaf_net._listener_sock:
        leaf_net._listener_sock.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestS2SLinkEstablishment:

    def test_hub_has_leaf_in_links(self, linked_pair):
        hub_net, leaf_net, hub_srv, leaf_srv = linked_pair
        with hub_net._lock:
            ids = [sid for sid, lnk in hub_net._links.items() if lnk.is_connected()]
        assert leaf_srv.server_id in ids, (
            f"Hub _links={list(hub_net._links.keys())} — expected {leaf_srv.server_id}"
        )

    def test_leaf_has_hub_in_links(self, linked_pair):
        hub_net, leaf_net, hub_srv, leaf_srv = linked_pair
        with leaf_net._lock:
            ids = [sid for sid, lnk in leaf_net._links.items() if lnk.is_connected()]
        assert hub_srv.server_id in ids, (
            f"Leaf _links={list(leaf_net._links.keys())} — expected {hub_srv.server_id}"
        )


class TestS2SBidirectionalRelay:

    def test_hub_to_leaf_syncmsg(self, linked_pair):
        """Message broadcast from hub arrives at leaf's broadcast_to_channel."""
        hub_net, leaf_net, hub_srv, leaf_srv = linked_pair

        hub_net.route_message("alice", "#general", "hello from hub")

        try:
            chan, msg = leaf_srv._received.get(timeout=5)
        except queue.Empty:
            pytest.fail("Leaf did not receive SYNCMSG from hub within 5s")

        assert "#general" in chan.lower(), f"Wrong channel: {chan}"
        assert "hello from hub" in msg, f"Wrong message content: {msg!r}"

    def test_leaf_to_hub_syncmsg(self, linked_pair):
        """Message broadcast from leaf arrives at hub's broadcast_to_channel."""
        hub_net, leaf_net, hub_srv, leaf_srv = linked_pair

        leaf_net.route_message("bob", "#general", "hello from leaf")

        try:
            chan, msg = hub_srv._received.get(timeout=5)
        except queue.Empty:
            pytest.fail("Hub did not receive SYNCMSG from leaf within 5s")

        assert "#general" in chan.lower(), f"Wrong channel: {chan}"
        assert "hello from leaf" in msg, f"Wrong message content: {msg!r}"

    def test_bidirectional_independent(self, linked_pair):
        """Both directions work simultaneously without interfering."""
        hub_net, leaf_net, hub_srv, leaf_srv = linked_pair

        # Drain any prior messages left from earlier tests in the same fixture
        time.sleep(0.3)
        while not hub_srv._received.empty():
            hub_srv._received.get_nowait()
        while not leaf_srv._received.empty():
            leaf_srv._received.get_nowait()

        hub_net.route_message("alice", "#relay", "from-hub")
        leaf_net.route_message("bob", "#relay", "from-leaf")

        try:
            _, leaf_got = leaf_srv._received.get(timeout=5)
        except queue.Empty:
            pytest.fail("Leaf did not receive hub->leaf relay")

        try:
            _, hub_got = hub_srv._received.get(timeout=5)
        except queue.Empty:
            pytest.fail("Hub did not receive leaf->hub relay")

        assert "from-hub" in leaf_got, f"Leaf got wrong content: {leaf_got!r}"
        assert "from-leaf" in hub_got, f"Hub got wrong content: {hub_got!r}"


class TestS2STiebreaker:
    """
    Verify tiebreaker does not break links when both ends
    simultaneously attempt outbound connections.
    """

    def test_simultaneous_connect_both_get_link(self):
        """
        Both servers connect to each other at the same time.
        After settling, both must have a connected link to the other.
        """
        from csc_server_core.server_network import ServerNetwork

        port_a = _free_udp_port()
        port_b = _free_udp_port()

        # Use IDs where alpha < zeta so tiebreaker is deterministic
        srv_a = FakeServer("haven.alpha")
        srv_b = FakeServer("haven.zeta")

        net_a = ServerNetwork(srv_a)
        net_b = ServerNetwork(srv_b)

        srv_a.s2s_network = net_a
        srv_b.s2s_network = net_b

        _PW = "testpass_tiebreaker"
        for net in (net_a, net_b):
            net.s2s_password = _PW
            net.s2s_role = "leaf"
            net.s2s_peers = []

        net_a.s2s_port = port_a
        net_b.s2s_port = port_b

        assert net_a.start_listener()
        assert net_b.start_listener()

        # Both attempt outbound at the same moment
        errors = []

        def _connect_a():
            try:
                net_a._try_link_to_peer("127.0.0.1", port_b)
            except Exception as e:
                errors.append(f"A: {e}")

        def _connect_b():
            try:
                net_b._try_link_to_peer("127.0.0.1", port_a)
            except Exception as e:
                errors.append(f"B: {e}")

        ta = threading.Thread(target=_connect_a, daemon=True)
        tb = threading.Thread(target=_connect_b, daemon=True)
        ta.start(); tb.start()
        ta.join(timeout=15); tb.join(timeout=15)

        assert not errors, f"Connect errors: {errors}"

        deadline = time.time() + 10
        while time.time() < deadline:
            a_links = [l for l in net_a._links.values() if l.is_connected()]
            b_links = [l for l in net_b._links.values() if l.is_connected()]
            if a_links and b_links:
                break
            time.sleep(0.1)

        # Teardown
        net_a._running = False; net_b._running = False
        if net_a._listener_sock: net_a._listener_sock.close()
        if net_b._listener_sock: net_b._listener_sock.close()

        a_ids = [sid for sid, l in net_a._links.items() if l.is_connected()]
        b_ids = [sid for sid, l in net_b._links.items() if l.is_connected()]

        assert srv_b.server_id in a_ids, (
            f"A._links={list(net_a._links.keys())} — expected {srv_b.server_id}"
        )
        assert srv_a.server_id in b_ids, (
            f"B._links={list(net_b._links.keys())} — expected {srv_a.server_id}"
        )


def _cleanup_vfs_key():
    """Remove vfs.key from cwd if present (test isolation)."""
    import pathlib
    vfs_key = pathlib.Path(os.getcwd()) / "vfs.key"
    if vfs_key.exists():
        vfs_key.unlink()


class TestS2SSyncKey:
    """VFS cipher key distribution via SYNCKEY."""

    def test_hub_key_delivered_to_leaf(self):
        """Hub's pre-configured VFS key arrives at leaf after link."""
        _cleanup_vfs_key()
        from csc_server_core.server_network import ServerNetwork

        KEY = "dd" * 32
        port_hub = _free_udp_port()
        port_leaf = _free_udp_port()

        hub_srv = FakeServer("haven.alpha")
        leaf_srv = FakeServer("haven.zeta")
        hub_net = ServerNetwork(hub_srv)
        leaf_net = ServerNetwork(leaf_srv)
        hub_srv.s2s_network = hub_net
        leaf_srv.s2s_network = leaf_net

        _PW = "testpass_keydeliver"
        for net in (hub_net, leaf_net):
            net.s2s_password = _PW
            net.s2s_role = "leaf"
            net.s2s_peers = []

        hub_net.s2s_port = port_hub
        leaf_net.s2s_port = port_leaf

        # Pre-configure key on hub BEFORE connecting
        hub_net.vfs_cipher_key = KEY
        hub_net._vfs_key_locked = True

        assert hub_net.start_listener()
        assert leaf_net.start_listener()

        t = threading.Thread(
            target=lambda: leaf_net._try_link_to_peer("127.0.0.1", port_hub),
            daemon=True,
        )
        t.start()

        # Wait for key to arrive at leaf
        deadline = time.time() + 10
        while time.time() < deadline:
            if leaf_net.vfs_cipher_key:
                break
            time.sleep(0.05)

        # Teardown
        hub_net._running = False
        leaf_net._running = False
        if hub_net._listener_sock:
            hub_net._listener_sock.close()
        if leaf_net._listener_sock:
            leaf_net._listener_sock.close()
        _cleanup_vfs_key()

        assert leaf_net.vfs_cipher_key == KEY, (
            f"Leaf key={leaf_net.vfs_cipher_key!r} != hub key={KEY!r}"
        )
        assert leaf_net._vfs_key_locked, "Leaf key should be locked after adoption"

    def test_key_locked_after_adoption(self):
        """Once a key is adopted, a conflicting key is rejected."""
        _cleanup_vfs_key()
        from csc_server_core.server_network import ServerNetwork

        port_a = _free_udp_port()
        port_b = _free_udp_port()

        KEY_A = "aa" * 32   # 32-byte key, hex
        KEY_B = "bb" * 32   # different key

        srv_a = FakeServer("haven.alpha")
        srv_b = FakeServer("haven.zeta")
        net_a = ServerNetwork(srv_a)
        net_b = ServerNetwork(srv_b)
        srv_a.s2s_network = net_a
        srv_b.s2s_network = net_b

        _PW = "testpass_synckey"
        for net in (net_a, net_b):
            net.s2s_password = _PW
            net.s2s_role = "leaf"
            net.s2s_peers = []

        net_a.s2s_port = port_a
        net_b.s2s_port = port_b

        # Pre-configure key A on net_a
        net_a.vfs_cipher_key = KEY_A
        net_a._vfs_key_locked = True

        assert net_a.start_listener()
        assert net_b.start_listener()

        # b connects to a — b should receive KEY_A
        t = threading.Thread(target=lambda: net_b._try_link_to_peer("127.0.0.1", port_a), daemon=True)
        t.start()

        deadline = time.time() + 10
        while time.time() < deadline:
            if net_b.vfs_cipher_key:
                break
            time.sleep(0.05)

        assert net_b.vfs_cipher_key == KEY_A, f"Expected KEY_A, got {net_b.vfs_cipher_key!r}"
        assert net_b._vfs_key_locked

        # Now try to push KEY_B to b — should be rejected
        rejected = not net_b.adopt_vfs_key(KEY_B, source_server_id="attacker")
        assert rejected, "Key conflict should have been rejected"
        assert net_b.vfs_cipher_key == KEY_A, "Key should still be KEY_A after rejection"

        # Teardown
        net_a._running = False; net_b._running = False
        if net_a._listener_sock: net_a._listener_sock.close()
        if net_b._listener_sock: net_b._listener_sock.close()
        _cleanup_vfs_key()

    def test_mesh_key_propagation(self):
        """Key propagates A->B->C in a chain (mesh routing)."""
        _cleanup_vfs_key()
        from csc_server_core.server_network import ServerNetwork

        KEY = "cc" * 32

        ports = [_free_udp_port() for _ in range(3)]
        servers = [FakeServer(f"haven.node{i}") for i in range(3)]
        nets = [ServerNetwork(s) for s in servers]

        for srv, net in zip(servers, nets):
            srv.s2s_network = net
            net.s2s_password = "testpass_mesh"
            net.s2s_role = "leaf"
            net.s2s_peers = []

        for i, (net, port) in enumerate(zip(nets, ports)):
            net.s2s_port = port
            assert net.start_listener()

        # Pre-configure key only on node 0 (hub); clear any disk-loaded key from nodes 1,2
        nets[0].vfs_cipher_key = KEY
        nets[0]._vfs_key_locked = True
        for net in nets[1:]:
            net.vfs_cipher_key = ""
            net._vfs_key_locked = False

        # Connect: node1 -> node0, node2 -> node1
        def _connect(leaf_net, hub_port):
            leaf_net._try_link_to_peer("127.0.0.1", hub_port)

        t1 = threading.Thread(target=_connect, args=(nets[1], ports[0]), daemon=True)
        t1.start()
        t1.join(timeout=10)

        t2 = threading.Thread(target=_connect, args=(nets[2], ports[1]), daemon=True)
        t2.start()
        t2.join(timeout=10)

        # Wait for key to propagate to node2 via node1
        deadline = time.time() + 10
        while time.time() < deadline:
            if nets[2].vfs_cipher_key:
                break
            time.sleep(0.05)

        # Teardown
        for net in nets:
            net._running = False
            if net._listener_sock:
                net._listener_sock.close()
        _cleanup_vfs_key()

        assert nets[1].vfs_cipher_key == KEY, f"Node1 missing key: {nets[1].vfs_cipher_key!r}"
        assert nets[2].vfs_cipher_key == KEY, f"Node2 missing key: {nets[2].vfs_cipher_key!r}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
