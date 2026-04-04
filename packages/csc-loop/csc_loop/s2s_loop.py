import time
import threading

class S2SAutoLinkLoop:
    """Maintains S2S links to configured peers."""

    def __init__(self, srv_ref, peers, project_root):
        self.srv_ref = srv_ref
        self.peers = peers
        self.project_root = project_root
        self._running = True

    def run(self):
        """Daemon loop: maintain S2S links."""
        time.sleep(10)  # let server and S2S listener fully start
        disconnect_file = self.project_root / "DISCONNECT"
        shutdown_file = self.project_root / "SHUTDOWN"

        while self._running and not shutdown_file.exists():
            try:
                if disconnect_file.exists():
                    for link in list(self.srv_ref.s2s_network._links.values()):
                        link.close()
                    self.srv_ref.s2s_network._links.clear()
                    self.srv_ref.log("[S2S] DISCONNECT file detected — all links dropped")
                    while disconnect_file.exists() and not shutdown_file.exists():
                        time.sleep(5)
                    if not shutdown_file.exists():
                        self.srv_ref.log("[S2S] DISCONNECT file removed — resuming auto-link")
                    continue

                for peer in self.peers:
                    host = peer.get("host", "")
                    port = peer.get("port", 9520)
                    if not host:
                        continue

                    already_linked = False
                    for sid, link in self.srv_ref.s2s_network._links.items():
                        if link._connected and link.remote_host == host:
                            already_linked = True
                            break

                    if not already_linked:
                        self.srv_ref.log(f"[S2S] Auto-linking to {host}:{port}...")
                        self.srv_ref.s2s_network.link_to(host, port)
            except Exception as e:
                self.srv_ref.log(f"[S2S] Auto-link error: {e}")
            time.sleep(30)

    def start(self):
        thread = threading.Thread(target=self.run, daemon=True)
        thread.start()
        return thread
