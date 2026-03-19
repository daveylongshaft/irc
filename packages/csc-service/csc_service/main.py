"""csc-service: unified service manager for CSC.

Usage:
    csc-service --daemon              # run all subsystems
    csc-service --daemon --local      # run on cwd (no clone)
    csc-service --daemon --dir /path  # run in specific directory
"""
import sys
import os
import time
import json
import threading
import subprocess
from pathlib import Path

def main():
    # Patch subprocess to auto-hide windows on Windows (before any subprocess calls)
    from csc_service.shared.subprocess_wrapper import patch_subprocess
    patch_subprocess()

    args = sys.argv[1:]

    # Walk up to find project root: check etc/csc-service.json and csc-service.json, fall back to CLAUDE.md
    csc_root = Path(__file__).resolve().parent
    claude_md_stop = None
    for _ in range(10):
        if (csc_root / "etc" / "csc-service.json").exists() or (csc_root / "csc-service.json").exists():
            break
        if (csc_root / "CLAUDE.md").exists() and claude_md_stop is None:
            claude_md_stop = csc_root  # remember but keep looking for csc-service.json
        if csc_root == csc_root.parent:
            csc_root = claude_md_stop or csc_root
            break
        csc_root = csc_root.parent
    work_dir = csc_root
    poll_interval = 60

    # Initialize Platform layer first - this sets up CSC_ETC, CSC_LOGS, etc.
    from csc_service.shared.platform import Platform
    plat = Platform()

    # Use Platform to get the etc/ path (handles Windows, Linux, Mac, etc.)
    config_file = plat.get_etc_dir() / "csc-service.json"
    if not config_file.exists():
        config_file = csc_root / "csc-service.json"
    config = {}
    if config_file.exists():
        try:
            config = json.loads(config_file.read_text(encoding='utf-8'))
        except Exception as e:
            print(f"[csc-service] WARNING: Failed to load config: {e}", flush=True)

    poll_interval = config.get("poll_interval", 60)
    enable_test_runner = config.get("enable_test_runner", True)
    enable_queue_worker = config.get("enable_queue_worker", True)
    enable_pm = config.get("enable_pm", True)
    enable_pr_review = config.get("enable_pr_review", False)
    enable_pki = config.get("enable_pki", False)
    enable_jules = config.get("jules", {}).get("enabled", False)
    enable_codex = config.get("codex", {}).get("enabled", False)
    enable_pki = config.get("enable_pki", False)
    enable_server = config.get("enable_server", True)
    enable_bridge = config.get("enable_bridge", False)

    from csc_service.infra import git_sync
    git_sync.setup(work_dir)

    try:
        if "--daemon" in args:
            # Write PID file
            pid_file = plat.run_dir / "csc-service.pid"
            pid_file.parent.mkdir(parents=True, exist_ok=True)
            pid_file.write_text(str(os.getpid()), encoding="utf-8")

            os.environ["CSC_HEADLESS"] = "true"

            ts = lambda: time.strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{ts()}] [csc-service] Starting (poll every {poll_interval}s)")
            
            # Start core threaded components (IRC server, Bridge, Clients)
            server_thread = None
            srv = None
            if enable_server:
                from csc_service.server.server import Server
                srv = Server()
                server_thread = threading.Thread(target=srv.run, daemon=True)
                server_thread.start()
                print(f"[{ts()}] [csc-service] Started IRC server")

                # Register #runtime channel + RuntimeBot + runtime.log
                def _setup_botserv_channels(srv_ref, project_root):
                    """Register BotServ channels and log files for IRC feeds."""
                    time.sleep(5)  # let server finish binding

                    logs_dir = project_root / "logs"
                    logs_dir.mkdir(parents=True, exist_ok=True)

                    # --- #runtime channel + RuntimeBot ---
                    srv_ref.channel_manager.ensure_channel("#runtime")
                    srv_ref.chanserv_register("#runtime", "davey", "Runtime activity feed")

                    srv_ref.botserv_register("#runtime", "RuntimeBot", "davey", "")
                    runtime_log = str(logs_dir / "runtime.log")
                    data = srv_ref.load_botserv()
                    rt_key = "#runtime:runtimebot"
                    rt_bot = data["bots"].get(rt_key, {})
                    rt_bot.setdefault("logs", [])
                    if runtime_log not in rt_bot["logs"]:
                        rt_bot["logs"].append(runtime_log)
                    rt_bot["logs_enabled"] = True
                    rt_bot.setdefault("channel", "#runtime")
                    rt_bot.setdefault("botnick", "RuntimeBot")
                    data["bots"][rt_key] = rt_bot

                    # --- #ftp channel + FTPBot ---
                    srv_ref.channel_manager.ensure_channel("#ftp")
                    srv_ref.chanserv_register("#ftp", "davey", "FTP operations feed")

                    srv_ref.botserv_register("#ftp", "FTPBot", "davey", "")
                    ftp_log = str(logs_dir / "ftp_announce.log")
                    ftp_key = "#ftp:ftpbot"
                    ftp_bot = data["bots"].get(ftp_key, {})
                    ftp_bot.setdefault("logs", [])
                    if ftp_log not in ftp_bot["logs"]:
                        ftp_bot["logs"].append(ftp_log)
                    ftp_bot["logs_enabled"] = True
                    ftp_bot.setdefault("channel", "#ftp")
                    ftp_bot.setdefault("botnick", "FTPBot")
                    data["bots"][ftp_key] = ftp_bot

                    srv_ref.save_botserv(data)

                    # Persist channels to disk so restore_all() won't remove them
                    srv_ref.save_channels_from_manager(srv_ref.channel_manager)

                setup_thread = threading.Thread(
                    target=_setup_botserv_channels, args=(srv, csc_root),
                    daemon=True
                )
                setup_thread.start()
                print(f"[{ts()}] [csc-service] Started BotServ channel registration (#runtime, #ftp)")

                # Start S2S auto-link thread if peers are configured
                s2s_peers = config.get("s2s_peers", [])
                if s2s_peers and hasattr(srv, 's2s_network'):
                    def _s2s_autolink_thread(srv_ref, peers, project_root):
                        """Daemon thread: maintain S2S links to configured peers."""
                        time.sleep(10)  # let server and S2S listener fully start
                        disconnect_file = project_root / "DISCONNECT"
                        while not (project_root / "SHUTDOWN").exists():
                            try:
                                if disconnect_file.exists():
                                    # DISCONNECT file present — drop all links, wait
                                    for link in list(srv_ref.s2s_network._links.values()):
                                        link.close()
                                    srv_ref.s2s_network._links.clear()
                                    srv_ref.log("[S2S] DISCONNECT file detected — all links dropped")
                                    while disconnect_file.exists() and not (project_root / "SHUTDOWN").exists():
                                        time.sleep(5)
                                    if not (project_root / "SHUTDOWN").exists():
                                        srv_ref.log("[S2S] DISCONNECT file removed — resuming auto-link")
                                    continue

                                # Check each configured peer
                                for peer in peers:
                                    host = peer.get("host", "")
                                    port = peer.get("port", 9520)
                                    if not host:
                                        continue
                                    # Check if already linked to this peer
                                    already_linked = False
                                    for sid, link in srv_ref.s2s_network._links.items():
                                        if link._connected and link.remote_host == host:
                                            already_linked = True
                                            break
                                    if not already_linked:
                                        srv_ref.log(f"[S2S] Auto-linking to {host}:{port}...")
                                        srv_ref.s2s_network.link_to(host, port)
                            except Exception as e:
                                srv_ref.log(f"[S2S] Auto-link error: {e}")
                            time.sleep(30)

                    autolink_thread = threading.Thread(
                        target=_s2s_autolink_thread, args=(srv, s2s_peers, csc_root),
                        daemon=True
                    )
                    autolink_thread.start()
                    print(f"[{ts()}] [csc-service] Started S2S auto-link thread ({len(s2s_peers)} peer(s))")

            # Start Bridge if enabled
            bridge_thread = None
            if enable_bridge:
                from csc_service.bridge.bridge import Bridge
                from csc_service.bridge.transports.tcp_inbound import TCPInbound
                from csc_service.bridge.transports.udp_inbound import UDPInbound
                from csc_service.bridge.transports.udp_outbound import UDPOutbound

                tcp_in = TCPInbound(
                    host=config.get("tcp_listen_host", "0.0.0.0"),
                    port=config.get("tcp_listen_port", 9667)
                )
                udp_in = UDPInbound(
                    host=config.get("udp_listen_host", "127.0.0.1"),
                    port=config.get("udp_listen_port", 9526)
                )
                outbound = UDPOutbound(
                    server_host=config.get("server_host", "127.0.0.1"),
                    server_port=config.get("server_port", 9525)
                )

                bridge = Bridge(
                    inbound_transports=[tcp_in, udp_in],
                    outbound_transport=outbound,
                    session_timeout=config.get("session_timeout", 300),
                    encrypt=config.get("bridge_encryption_enabled", True),
                    normalize_mode=config.get("gateway_mode", None),
                )
                bridge.start()
                print(f"[{ts()}] [csc-service] Started IRC bridge")
            # Start FTP daemon if enabled
            ftpd_config = config.get("ftpd", {})
            if ftpd_config.get("enabled", False):
                try:
                    from csc_service.ftpd.ftp_config import FtpConfig
                    ftpd_cfg = FtpConfig(config_dict=ftpd_config, csc_root=csc_root)
                    ok, reason = ftpd_cfg.validate()
                    if ok:
                        if ftpd_cfg.is_master:
                            from csc_service.ftpd.ftp_master import FtpMaster
                            ftpd_master = FtpMaster(ftpd_cfg)
                            ftpd_master.start()
                            print(f"[{ts()}] [csc-service] Started FTP master (ftp={ftpd_cfg.ftp_control_port}, slaves={ftpd_cfg.master_control_port})")
                            # Wire announce callback for FTP master handler
                            if srv:
                                ftpd_master.server._ftpd_announce_callback = srv.ftp_announce
                        else:
                            from csc_service.ftpd.ftp_slave import FtpSlave
                            ftpd_slave = FtpSlave(ftpd_cfg)
                            ftpd_slave.start()
                            print(f"[{ts()}] [csc-service] Started FTP slave (master={ftpd_cfg.master_host}:{ftpd_cfg.master_control_port})")
                            # Wire announce callback for FTP slave
                            if srv:
                                ftpd_slave.set_announce_callback(srv.ftp_announce)
                            # Wire S2S bridge for peer-to-peer file sync
                            if hasattr(srv, 's2s_network'):
                                try:
                                    from csc_service.ftpd.ftp_s2s_bridge import FtpS2sBridge
                                    fxp_bridge = FtpS2sBridge(ftpd_slave, srv.s2s_network)
                                    ftpd_slave.set_s2s_bridge(fxp_bridge)
                                    srv.s2s_network.attach_fxp_bridge(fxp_bridge)
                                    print(f"[{ts()}] [csc-service] FXP S2S bridge attached")
                                except Exception as e:
                                    print(f"[{ts()}] [csc-service] FXP bridge setup failed: {e}")
                    else:
                        print(f"[{ts()}] [csc-service] FTPD config invalid: {reason}")
                except ImportError as e:
                    print(f"[{ts()}] [csc-service] FTPD requires pyftpdlib: {e}")
                except Exception as e:
                    print(f"[{ts()}] [csc-service] FTPD startup failed: {e}")

            # Start PKI enrollment server if enabled (CA server only)
            if enable_pki:
                from csc_service.pki import main as pki_main
                pki_main.start()
                print(f"[{ts()}] [csc-service] Started PKI enrollment server")

            # Daemon main loop for infra services (smart backpressure)
            try:
                from csc_service.shared.platform import Platform
                idle_cycles = 0
                while True:
                    # SHUTDOWN Kill Switch
                    if (Platform.PROJECT_ROOT / "SHUTDOWN").exists():
                        print(f"[{ts()}] [csc-service] SHUTDOWN kill switch detected. Terminating immediately.")
                        sys.exit(0)

                    git_sync.pull()

                    had_work = False

                    if enable_test_runner:
                        try:
                            from csc_service.infra import test_runner
                            if test_runner.run_cycle(work_dir):
                                had_work = True
                        except Exception as e:
                            print(f"[{ts()}] [test-runner] ERROR: {e}")

                    if enable_queue_worker:
                        try:
                            from csc_service.infra import queue_worker
                            if queue_worker.run_cycle(work_dir):
                                had_work = True
                        except Exception as e:
                            print(f"[{ts()}] [queue-worker] ERROR: {e}")

                    if enable_pm:
                        try:
                            from csc_service.infra import pm
                            pm.setup(work_dir)
                            if pm.run_cycle():
                                had_work = True
                                # If PM just assigned something, pick it up immediately
                                if enable_queue_worker:
                                    try:
                                        if queue_worker.run_cycle(work_dir):
                                            had_work = True
                                    except Exception as e:
                                        print(f"[{ts()}] [queue-worker] ERROR: {e}")
                        except Exception as e:
                            print(f"[{ts()}] [pm] ERROR: {e}")

                    if enable_pr_review:
                        try:
                            from csc_service.infra import pr_review
                            if pr_review.run_cycle(work_dir):
                                had_work = True
                        except Exception as e:
                            print(f"[{ts()}] [pr-review] ERROR: {e}")

                    if enable_jules:
                        try:
                            from csc_service.infra import jules_monitor
                            if jules_monitor.run_cycle(work_dir):
                                had_work = True
                        except Exception as e:
                            print(f"[{ts()}] [jules] ERROR: {e}")

                    if enable_codex:
                        try:
                            from csc_service.infra import codex_monitor
                            if codex_monitor.run_cycle(work_dir):
                                had_work = True
                        except Exception as e:
                            print(f"[{ts()}] [codex] ERROR: {e}")

                    git_sync.push_if_changed()

                    # Smart backpressure: fast loop while work flows, slow when idle
                    if had_work:
                        idle_cycles = 0
                        # Continue immediately to next cycle
                    else:
                        idle_cycles += 1
                        if idle_cycles >= 3:
                            # 3+ idle cycles -> fall back to slow polling
                            time.sleep(poll_interval)
                            idle_cycles = 0
                        # else: keep cycling fast for a few attempts

            except KeyboardInterrupt:
                print(f"\n[{ts()}] [csc-service] Stopped")
        else:
            print(__doc__)

    except Exception as e:
        ts = lambda: time.strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts()}] [csc-service] FATAL ERROR during execution: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
