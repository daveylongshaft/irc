"""FTP IRC handler mixin.

Provides an IRCop-only control surface over the FTP daemon's virtual
filesystem. The wire command is:

    FTP <SUBCOMMAND> [args...]

Server responses are sent as NOTICE lines:

    NOTICE <nick> :FTP PRET <ip> <port> <action> [size]
    NOTICE <nick> :FTP CWD <path>
    NOTICE <nick> :FTP PWD <path>
    NOTICE <nick> :FTP SIZE <path> <size>
    NOTICE <nick> :FTP OK <message>
    NOTICE <nick> :FTP ERR <message>
"""

from __future__ import annotations

import json
import hashlib
import os
import posixpath
import select
import socket
import uuid
from pathlib import Path
from types import SimpleNamespace


def _server_shortname() -> str:
    try:
        from csc_platform import Platform
        return Platform.get_server_shortname() or "server"
    except Exception:
        return os.environ.get("CSC_SERVER_ID", "server")


class FTPMixin:
    """Mixin for MessageHandler: handles the FTP IRC command."""

    _ftp_cwd: dict
    _ftp_rnfr: dict
    _ftp_config_cache = None
    _ftp_index_cache = None

    def _ftp_init(self):
        if not hasattr(self, "_ftp_cwd"):
            self._ftp_cwd = {}
        if not hasattr(self, "_ftp_rnfr"):
            self._ftp_rnfr = {}

    def _handle_ftp(self, msg, addr):
        self._ftp_init()
        nick = self._get_nick(addr)
        if not nick:
            return

        params = msg.params if hasattr(msg, "params") else []
        trailing = msg.trailing if hasattr(msg, "trailing") else ""
        args = list(params) + ([trailing] if trailing else [])
        sub = args[0].upper() if args else ""
        rest = args[1:] if len(args) > 1 else []

        if not self._ftp_is_allowed(nick):
            self._ftp_err(addr, nick, "IRC operator privileges are required to use FTP.")
            self._ftp_log("deny", nick=nick, path=(rest[0] if rest else ""), detail="not-oper")
            return

        dispatch = {
            "LIST": self._ftp_list,
            "LS": self._ftp_list,
            "CWD": self._ftp_cwd_cmd,
            "PWD": self._ftp_pwd_cmd,
            "SIZE": self._ftp_size_cmd,
            "GET": self._ftp_get,
            "PUT": self._ftp_put,
            "RNFR": self._ftp_rnfr_cmd,
            "RNTO": self._ftp_rnto_cmd,
            "MV": self._ftp_mv_cmd,
            "DEL": self._ftp_del,
        }
        handler = dispatch.get(sub)
        if handler:
            handler(nick, addr, rest)
        else:
            self._ftp_err(addr, nick, f"Unknown FTP subcommand: {sub}")

    def _ftp_is_allowed(self, nick: str) -> bool:
        return nick.lower() in getattr(self.server, "opers", {})

    def _ftp_notice(self, addr, nick: str, text: str):
        self.server.sock_send(f":server NOTICE {nick} :{text}\r\n".encode(), addr)

    def _ftp_pret(self, addr, nick: str, ip: str, port: int, action: str, extra: str = ""):
        suffix = f" {extra}" if extra else ""
        self._ftp_notice(addr, nick, f"FTP PRET {ip} {port} {action}{suffix}")

    def _ftp_ok(self, addr, nick: str, message: str):
        self._ftp_notice(addr, nick, f"FTP OK {message}")

    def _ftp_err(self, addr, nick: str, message: str):
        self._ftp_notice(addr, nick, f"FTP ERR {message}")

    def _ftp_log(self, action: str, nick: str, path: str = "", detail: str = ""):
        suffix = f" detail={detail}" if detail else ""
        self.server.log(f"[FTP] action={action} nick={nick} path={path}{suffix}")

    def _ftp_get_config(self):
        if self._ftp_config_cache is not None:
            return self._ftp_config_cache
        try:
            from csc_ftpd.ftp_config import FtpConfig
            self._ftp_config_cache = FtpConfig()
        except Exception as exc:
            self.server.log(f"[FTP] csc_ftpd unavailable, using local fallback config: {exc}")
            self._ftp_config_cache = self._ftp_fallback_config()
        return self._ftp_config_cache or None

    def _ftp_fallback_config(self):
        root = self._ftp_find_csc_root()
        service_path = self._ftp_find_service_config(root)
        raw = {}
        if service_path is not None:
            try:
                raw = json.loads(service_path.read_text(encoding="utf-8")).get("ftpd", {})
            except Exception as exc:
                self.server.log(f"[FTP] Failed to read fallback ftpd config from {service_path}: {exc}")

        serve_root = raw.get("serve_root") or str(root)
        serve_root = str(Path(serve_root).resolve())
        index_path = raw.get("index_path", "etc/ftpd_index.json")
        users_path = raw.get("users_path", "etc/ftpd_users.json")

        return SimpleNamespace(
            enabled=raw.get("enabled", False),
            role=raw.get("role", "slave"),
            master_host=raw.get("master_host", "10.10.10.1"),
            serve_root=serve_root,
            index_path=str((root / index_path).resolve()) if not os.path.isabs(index_path) else index_path,
            users_path=str((root / users_path).resolve()) if not os.path.isabs(users_path) else users_path,
        )

    def _ftp_find_csc_root(self) -> Path:
        env_root = os.environ.get("CSC_ROOT") or os.environ.get("CSC_HOME")
        candidates = []
        if env_root:
            candidates.append(Path(env_root))
        candidates.extend([Path.cwd(), Path(__file__).resolve()])
        for candidate in candidates:
            current = candidate if candidate.is_dir() else candidate.parent
            for _ in range(12):
                if (current / "csc-service.json").exists() or (current / "etc" / "csc-service.json").exists():
                    return current
                if current == current.parent:
                    break
                current = current.parent
        return Path.cwd()

    def _ftp_find_service_config(self, root: Path) -> Path | None:
        for candidate in (root / "etc" / "csc-service.json", root / "csc-service.json"):
            if candidate.exists():
                return candidate
        return None

    def _ftp_get_index(self):
        live_index = getattr(self.server, "_ftpd_index", None)
        if live_index is not None:
            return live_index
        if self._ftp_index_cache is not None:
            return self._ftp_index_cache or None
        config = self._ftp_get_config()
        if not config or getattr(config, "role", "") != "master":
            self._ftp_index_cache = False
            return None
        try:
            from csc_ftpd.ftp_master_index import FtpMasterIndex
            self._ftp_index_cache = FtpMasterIndex(config.index_path)
        except Exception:
            self._ftp_index_cache = False
        return self._ftp_index_cache or None

    def _ftp_resolve(self, nick: str, path: str | None) -> str:
        raw = (path or "").strip()
        if raw.startswith("ftp:"):
            raw = raw[4:]
        if not raw:
            raw = self._ftp_cwd.get(nick, "/")
        elif not raw.startswith("/"):
            raw = posixpath.join(self._ftp_cwd.get(nick, "/"), raw)
        norm = posixpath.normpath(raw.replace("\\", "/"))
        if not norm.startswith("/"):
            norm = "/" + norm
        return norm

    def _ftp_local_root(self) -> Path | None:
        config = self._ftp_get_config()
        if not config:
            return None
        try:
            return Path(config.serve_root).resolve()
        except Exception:
            return None

    def _ftp_local_path(self, vpath: str) -> Path:
        root = self._ftp_local_root()
        if root is None:
            raise RuntimeError("FTPD is not configured")
        candidate = (root / vpath.lstrip("/").replace("/", os.sep)).resolve()
        if candidate != root and root not in candidate.parents:
            raise PermissionError("Path escapes FTP root")
        return candidate

    def _ftp_is_dir(self, vpath: str) -> bool:
        index = self._ftp_get_index()
        if index is not None:
            if vpath == "/":
                return True
            prefix = vpath.rstrip("/") + "/"
            return any(path.startswith(prefix) for path in index.all_paths())
        local = self._ftp_local_path(vpath)
        return local.exists() and local.is_dir()

    def _ftp_exists(self, vpath: str) -> bool:
        index = self._ftp_get_index()
        if index is not None:
            return bool(index.lookup(vpath)) or self._ftp_is_dir(vpath)
        return self._ftp_local_path(vpath).exists()

    def _ftp_size(self, vpath: str) -> int:
        index = self._ftp_get_index()
        if index is not None:
            slaves = index.lookup(vpath)
            if slaves:
                best = max(slaves.values(), key=lambda s: s.get("mtime", 0))
                return int(best.get("size", 0))
        local = self._ftp_local_path(vpath)
        if not local.exists() or not local.is_file():
            raise FileNotFoundError(vpath)
        return local.stat().st_size

    def _ftp_listing_bytes(self, vpath: str) -> bytes:
        index = self._ftp_get_index()
        if index is not None:
            entries = index.list_dir(vpath)
            lines = []
            for entry in entries:
                marker = "/" if entry.get("is_dir") else ""
                size = entry.get("size", 0)
                lines.append(f"{entry['name']}{marker}\t{size}")
            lines.append(f"({len(entries)} item(s) at {vpath})")
            return "\n".join(lines).encode("utf-8")

        local = self._ftp_local_path(vpath)
        if not local.exists() or not local.is_dir():
            raise FileNotFoundError(vpath)
        entries = []
        for child in sorted(local.iterdir(), key=lambda p: p.name.lower()):
            suffix = "/" if child.is_dir() else ""
            size = child.stat().st_size if child.is_file() else 0
            entries.append(f"{child.name}{suffix}\t{size}")
        entries.append(f"({len(entries)} item(s) at {vpath})")
        return "\n".join(entries).encode("utf-8")

    def _ftp_update_index_for_local_file(self, vpath: str):
        config = self._ftp_get_config()
        if not config or getattr(config, "role", "") != "master":
            return
        index = self._ftp_get_index()
        if index is None:
            return
        local = self._ftp_local_path(vpath)
        if not local.exists() or not local.is_file():
            return
        with open(local, "rb") as handle:
            digest = hashlib.md5(handle.read()).hexdigest()
        info = {
            "path": vpath,
            "size": local.stat().st_size,
            "mtime": local.stat().st_mtime,
            "md5": digest,
        }
        index.apply_delta(_server_shortname(), added=[info])

    def _ftp_remove_index_for_local_file(self, vpath: str):
        config = self._ftp_get_config()
        if not config or getattr(config, "role", "") != "master":
            return
        index = self._ftp_get_index()
        if index is not None:
            index.apply_delta(_server_shortname(), removed=[vpath])

    def _ftp_trigger_sync(self):
        slave = getattr(self.server, "_ftpd_slave", None)
        if slave and hasattr(slave, "schedule_inventory_delta"):
            try:
                slave.schedule_inventory_delta()
            except Exception:
                self.server.log("[FTP] schedule_inventory_delta failed")

    def _ftp_pwd_cmd(self, nick: str, addr, _args: list):
        self._ftp_notice(addr, nick, f"FTP PWD {self._ftp_cwd.get(nick, '/')}")

    def _ftp_cwd_cmd(self, nick: str, addr, args: list):
        if not args:
            self._ftp_err(addr, nick, "CWD requires a path")
            return
        vpath = self._ftp_resolve(nick, args[0])
        try:
            if not self._ftp_is_dir(vpath):
                raise FileNotFoundError(vpath)
            self._ftp_cwd[nick] = vpath
            self._ftp_notice(addr, nick, f"FTP CWD {vpath}")
            self._ftp_log("cwd", nick=nick, path=vpath)
        except Exception as exc:
            self._ftp_err(addr, nick, f"CWD failed: {exc}")

    def _ftp_list(self, nick: str, addr, args: list):
        vpath = self._ftp_resolve(nick, args[0] if args else "")
        from csc_server_core.vfs_data_conn import VFSDataConn

        try:
            payload = self._ftp_listing_bytes(vpath)
            conn = VFSDataConn()
            self._ftp_pret(addr, nick, conn.ip, conn.port, "LIST")
            conn.serve_download(
                payload,
                on_done=lambda: self._ftp_ok(addr, nick, f"LIST {vpath}"),
                on_error=lambda e: self._ftp_err(addr, nick, f"LIST failed: {e}"),
            )
            self._ftp_log("list", nick=nick, path=vpath)
        except Exception as exc:
            self._ftp_err(addr, nick, f"LIST setup failed: {exc}")

    def _ftp_size_cmd(self, nick: str, addr, args: list):
        if not args:
            self._ftp_err(addr, nick, "SIZE requires a path")
            return
        vpath = self._ftp_resolve(nick, args[0])
        try:
            size = self._ftp_size(vpath)
            self._ftp_notice(addr, nick, f"FTP SIZE {vpath} {size}")
            self._ftp_log("size", nick=nick, path=vpath)
        except Exception as exc:
            self._ftp_err(addr, nick, f"SIZE failed: {exc}")

    def _ftp_get(self, nick: str, addr, args: list):
        if not args:
            self._ftp_err(addr, nick, "GET requires a path")
            return
        vpath = self._ftp_resolve(nick, args[0])
        size = self._ftp_size(vpath)
        from csc_server_core.vfs_data_conn import VFSDataConn

        try:
            conn = VFSDataConn()
            self._ftp_pret(addr, nick, conn.ip, conn.port, "GET", str(size))
            if self._ftp_can_stream_via_master(vpath):
                conn.serve_download_stream(
                    lambda client_sock: self._ftp_master_stream_download(vpath, client_sock),
                    on_done=lambda: self._ftp_ok(addr, nick, f"GET {vpath}"),
                    on_error=lambda e: self._ftp_err(addr, nick, f"GET failed: {e}"),
                )
            else:
                local = self._ftp_local_path(vpath)
                conn.serve_download_stream(
                    lambda client_sock: self._ftp_stream_local_file(local, client_sock),
                    on_done=lambda: self._ftp_ok(addr, nick, f"GET {vpath}"),
                    on_error=lambda e: self._ftp_err(addr, nick, f"GET failed: {e}"),
                )
            self._ftp_log("get", nick=nick, path=vpath, detail=f"size={size}")
        except Exception as exc:
            self._ftp_err(addr, nick, f"GET setup failed: {exc}")

    def _ftp_put(self, nick: str, addr, args: list):
        if not args:
            self._ftp_err(addr, nick, "PUT requires a path")
            return
        vpath = self._ftp_resolve(nick, args[0])
        from csc_server_core.vfs_data_conn import VFSDataConn

        try:
            conn = VFSDataConn()
            self._ftp_pret(addr, nick, conn.ip, conn.port, "PUT")
            if self._ftp_can_stream_via_master_upload():
                conn.serve_upload_stream(
                    lambda client_sock: self._ftp_master_stream_upload(vpath, client_sock),
                    on_done=lambda: self._ftp_ok(addr, nick, f"PUT {vpath}"),
                    on_error=lambda e: self._ftp_err(addr, nick, f"PUT failed: {e}"),
                )
            else:
                conn.serve_upload_stream(
                    lambda client_sock: self._ftp_receive_local_file(vpath, client_sock),
                    on_done=lambda: self._ftp_ok(addr, nick, f"PUT {vpath}"),
                    on_error=lambda e: self._ftp_err(addr, nick, f"PUT failed: {e}"),
                )
            self._ftp_log("put", nick=nick, path=vpath)
        except Exception as exc:
            self._ftp_err(addr, nick, f"PUT setup failed: {exc}")

    def _ftp_rnfr_cmd(self, nick: str, addr, args: list):
        if not args:
            self._ftp_err(addr, nick, "RNFR requires a path")
            return
        vpath = self._ftp_resolve(nick, args[0])
        if not self._ftp_exists(vpath):
            self._ftp_err(addr, nick, f"Not found: {vpath}")
            return
        self._ftp_rnfr[nick] = vpath
        self._ftp_ok(addr, nick, f"RNFR staged: {vpath}")
        self._ftp_log("rnfr", nick=nick, path=vpath)

    def _ftp_rnto_cmd(self, nick: str, addr, args: list):
        if not args:
            self._ftp_err(addr, nick, "RNTO requires a path")
            return
        src = self._ftp_rnfr.pop(nick, None)
        if not src:
            self._ftp_err(addr, nick, "RNTO requires a prior RNFR")
            return
        dst = self._ftp_resolve(nick, args[0])
        try:
            self._ftp_rename(src, dst)
            self._ftp_ok(addr, nick, f"RENAMED {src} -> {dst}")
            self._ftp_log("rename", nick=nick, path=src, detail=f"dst={dst}")
        except Exception as exc:
            self._ftp_err(addr, nick, f"RNTO failed: {exc}")

    def _ftp_mv_cmd(self, nick: str, addr, args: list):
        if len(args) < 2:
            self._ftp_err(addr, nick, "MV requires source and destination")
            return
        src = self._ftp_resolve(nick, args[0])
        dst = self._ftp_resolve(nick, args[1])
        try:
            self._ftp_rename(src, dst)
            self._ftp_ok(addr, nick, f"MOVED {src} -> {dst}")
            self._ftp_log("mv", nick=nick, path=src, detail=f"dst={dst}")
        except Exception as exc:
            self._ftp_err(addr, nick, f"MV failed: {exc}")

    def _ftp_del(self, nick: str, addr, args: list):
        if not args:
            self._ftp_err(addr, nick, "DEL requires a path")
            return
        vpath = self._ftp_resolve(nick, args[0])
        try:
            self._ftp_delete(vpath)
            self._ftp_ok(addr, nick, f"DELETED {vpath}")
            self._ftp_log("delete", nick=nick, path=vpath)
        except Exception as exc:
            self._ftp_err(addr, nick, f"DEL failed: {exc}")

    def _ftp_stream_local_file(self, local_path: Path, client_sock):
        with open(local_path, "rb") as handle:
            while True:
                chunk = handle.read(65536)
                if not chunk:
                    break
                client_sock.sendall(chunk)

    def _ftp_receive_local_file(self, vpath: str, client_sock):
        local = self._ftp_local_path(vpath)
        local.parent.mkdir(parents=True, exist_ok=True)
        tmp = local.with_suffix(local.suffix + ".ftp.tmp")
        total = 0
        try:
            with open(tmp, "wb") as handle:
                while True:
                    chunk = client_sock.recv(65536)
                    if not chunk:
                        break
                    handle.write(chunk)
                    total += len(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            if os.name == "nt" and local.exists():
                local.unlink()
            tmp.rename(local)
            self._ftp_trigger_sync()
            self._ftp_update_index_for_local_file(vpath)
            self.server.log(f"[FTP] stored {vpath} bytes={total}")
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass

    def _ftp_can_stream_via_master(self, vpath: str) -> bool:
        master = getattr(self.server, "_ftpd_master", None)
        index = getattr(self.server, "_ftpd_index", None)
        return master is not None and index is not None and bool(index.lookup(vpath))

    def _ftp_can_stream_via_master_upload(self) -> bool:
        master = getattr(self.server, "_ftpd_master", None)
        return master is not None and hasattr(master, "pick_slave_for_upload")

    def _ftp_make_master_relay_listener(self):
        config = getattr(self.server, "_ftpd_config", None)
        if config is not None:
            low, high = config.passive_range
            for port in range(low, high + 1):
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    sock.bind(("0.0.0.0", port))
                    sock.listen(1)
                    return sock
                except OSError:
                    continue
            raise RuntimeError("No relay port available")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", 0))
        sock.listen(1)
        return sock

    def _ftp_master_stream_download(self, vpath: str, client_sock):
        master = self.server._ftpd_master
        index = self.server._ftpd_index
        slave_id = index.pick_slave(vpath)
        if slave_id is None:
            raise FileNotFoundError(vpath)
        slave_conn = master.get_slave(slave_id)
        if slave_conn is None or not slave_conn.connected:
            raise RuntimeError(f"Slave offline for {vpath}")
        relay_sock = self._ftp_make_master_relay_listener()
        transfer_id = str(uuid.uuid4())[:8]
        relay_host, relay_port = relay_sock.getsockname()
        try:
            slave_conn.send_file(transfer_id, vpath, relay_host, relay_port)
            relay_sock.settimeout(30)
            slave_data, _ = relay_sock.accept()
            try:
                slave_data.settimeout(60)
                while True:
                    ready, _, _ = select.select([slave_data], [], [], 30)
                    if not ready:
                        break
                    chunk = slave_data.recv(65536)
                    if not chunk:
                        break
                    client_sock.sendall(chunk)
            finally:
                slave_data.close()
        finally:
            relay_sock.close()

    def _ftp_master_stream_upload(self, vpath: str, client_sock):
        master = self.server._ftpd_master
        slave_id = master.pick_slave_for_upload()
        if slave_id is None:
            raise RuntimeError("No FTP slave available for upload")
        slave_conn = master.get_slave(slave_id)
        if slave_conn is None or not slave_conn.connected:
            raise RuntimeError("Target FTP slave is offline")
        relay_sock = self._ftp_make_master_relay_listener()
        transfer_id = str(uuid.uuid4())[:8]
        relay_host, relay_port = relay_sock.getsockname()
        try:
            slave_conn.recv_file(transfer_id, vpath, relay_host, relay_port)
            relay_sock.settimeout(30)
            slave_data, _ = relay_sock.accept()
            try:
                slave_data.settimeout(60)
                while True:
                    ready, _, _ = select.select([client_sock], [], [], 30)
                    if not ready:
                        break
                    chunk = client_sock.recv(65536)
                    if not chunk:
                        break
                    slave_data.sendall(chunk)
            finally:
                slave_data.close()
        finally:
            relay_sock.close()

    def _ftp_delete(self, vpath: str):
        master = getattr(self.server, "_ftpd_master", None)
        index = getattr(self.server, "_ftpd_index", None)
        if master is not None and index is not None:
            slaves = index.lookup(vpath)
            if not slaves:
                raise FileNotFoundError(vpath)
            for sid in slaves:
                conn = master.get_slave(sid)
                if conn and conn.connected:
                    conn.delete_file(vpath)
            for sid in slaves:
                index.apply_delta(sid, removed=[vpath])
            return

        local = self._ftp_local_path(vpath)
        if not local.exists():
            raise FileNotFoundError(vpath)
        if local.is_dir():
            raise IsADirectoryError(vpath)
        local.unlink()
        self._ftp_trigger_sync()
        self._ftp_remove_index_for_local_file(vpath)

    def _ftp_rename(self, src: str, dst: str):
        master = getattr(self.server, "_ftpd_master", None)
        index = getattr(self.server, "_ftpd_index", None)
        if master is not None and index is not None:
            slaves = index.lookup(src)
            if not slaves:
                raise FileNotFoundError(src)
            for sid in slaves:
                conn = master.get_slave(sid)
                if conn and conn.connected:
                    conn.rename_file(src, dst)
            index.rename_entry(src, dst)
            return

        src_local = self._ftp_local_path(src)
        dst_local = self._ftp_local_path(dst)
        if not src_local.exists():
            raise FileNotFoundError(src)
        dst_local.parent.mkdir(parents=True, exist_ok=True)
        if os.name == "nt" and dst_local.exists():
            dst_local.unlink()
        src_local.rename(dst_local)
        self._ftp_trigger_sync()
        self._ftp_remove_index_for_local_file(src)
        self._ftp_update_index_for_local_file(dst)
