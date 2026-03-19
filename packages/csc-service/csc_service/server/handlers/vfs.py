"""VFS IRC handler mixin — browse, encrypt, decrypt, list, cat, rename.

IRC protocol:
    Client sends:  VFS <SUBCOMMAND> [args...]
    Server sends:  NOTICE <nick> :VFS PRET <ip> <port> <action>   (for transfers)
                   NOTICE <nick> :VFS CAT <line>                   (inline text)
                   NOTICE <nick> :VFS CAT END
                   NOTICE <nick> :VFS CWD <pathspec>               (cwd confirm)
                   NOTICE <nick> :VFS OK <message>
                   NOTICE <nick> :VFS ERR <message>

Subcommands:
    VFS LIST [pathspec]               — list files at pathspec prefix
    VFS CWD <pathspec>                — set working prefix for this nick
    VFS ENCRYPT <pathspec>            — PRET upload; client sends raw file bytes
    VFS DECRYPT <pathspec>            — PRET download; server sends plaintext
    VFS CAT <pathspec>                — inline text read (NOTICE per line)
    VFS RNFR <pathspec>               — rename from (stage)
    VFS RNTO <pathspec>               — rename to (complete)
    VFS DEL <pathspec>                — delete encrypted file

ACL policy:
    Writes (ENCRYPT, RNFR/RNTO, DEL) require NickServ-identified nick or oper.
    Reads (LIST, DECRYPT, CAT) also require identified nick or oper.
    Server-internal calls use the server shortname as requester.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path


def _get_vfs():
    """Lazy-load VirtualFileSystem pointed at csc_root/vfs/."""
    from csc_data._enc_vfs import find_csc_root
    from enc_ext_vfs.vfs import VirtualFileSystem
    root = find_csc_root() / "vfs"
    root.mkdir(parents=True, exist_ok=True)
    return VirtualFileSystem(str(root))


def _server_shortname() -> str:
    try:
        from csc_data._enc_vfs import find_csc_root
        name = (find_csc_root() / "server_name").read_text(encoding="utf-8").strip()
        return name or "server"
    except Exception:
        return os.environ.get("CSC_SERVER_ID", "server")


class VFSMixin:
    """Mixin for MessageHandler: handles the VFS IRC command."""

    # Per-nick state: current working prefix and pending RNFR path
    _vfs_cwd: dict   # nick -> pathspec prefix (e.g. "logs::haven.ef6e::")
    _vfs_rnfr: dict  # nick -> pathspec (pending rename-from)

    def _vfs_init(self):
        if not hasattr(self, "_vfs_cwd"):
            self._vfs_cwd = {}
        if not hasattr(self, "_vfs_rnfr"):
            self._vfs_rnfr = {}

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def _handle_vfs(self, msg, addr):
        self._vfs_init()
        nick = self._get_nick(addr)
        if not nick:
            return

        params = msg.params if hasattr(msg, "params") else []
        trailing = msg.trailing if hasattr(msg, "trailing") else ""
        # VFS LIST logs::haven.ef6e::  →  params=['LIST', 'logs::haven.ef6e::']
        args = list(params) + ([trailing] if trailing else [])
        sub = args[0].upper() if args else ""
        rest = args[1:] if len(args) > 1 else []

        # Auth check: all VFS operations require identification
        if not self._vfs_is_allowed(nick, addr):
            self._vfs_err(addr, nick, "You must be NickServ-identified or an IRC operator to use VFS.")
            return

        dispatch = {
            "LIST":    self._vfs_list,
            "CWD":     self._vfs_cwd_cmd,
            "ENCRYPT": self._vfs_encrypt,
            "DECRYPT": self._vfs_decrypt,
            "CAT":     self._vfs_cat,
            "RNFR":    self._vfs_rnfr_cmd,
            "RNTO":    self._vfs_rnto_cmd,
            "DEL":     self._vfs_del,
        }
        handler = dispatch.get(sub)
        if handler:
            handler(nick, addr, rest)
        else:
            self._vfs_err(addr, nick, f"Unknown VFS subcommand: {sub}. Try LIST, CWD, ENCRYPT, DECRYPT, CAT, RNFR, RNTO, DEL")

    # ------------------------------------------------------------------
    # Auth helpers
    # ------------------------------------------------------------------

    def _vfs_is_allowed(self, nick: str, addr) -> bool:
        """Allow if NickServ-identified or oper."""
        identified = getattr(self.server, "nickserv_identified", {})
        if identified.get(addr) == nick:
            return True
        opers = getattr(self.server, "opers", {})
        if nick in opers:
            return True
        return False

    def _vfs_requester(self, nick: str, addr) -> str:
        """Return requester id: identified nick, or server shortname for internal."""
        identified = getattr(self.server, "nickserv_identified", {})
        if identified.get(addr) == nick:
            return nick
        return _server_shortname()

    # ------------------------------------------------------------------
    # Send helpers
    # ------------------------------------------------------------------

    def _vfs_notice(self, addr, nick: str, text: str):
        msg = f":server NOTICE {nick} :{text}\r\n"
        self.server.sock_send(msg.encode(), addr)

    def _vfs_pret(self, addr, nick: str, ip: str, port: int, action: str):
        self._vfs_notice(addr, nick, f"VFS PRET {ip} {port} {action}")

    def _vfs_ok(self, addr, nick: str, message: str):
        self._vfs_notice(addr, nick, f"VFS OK {message}")

    def _vfs_err(self, addr, nick: str, message: str):
        self._vfs_notice(addr, nick, f"VFS ERR {message}")

    def _vfs_resolve(self, nick: str, pathspec: str) -> str:
        """Resolve pathspec relative to nick's working prefix if not absolute."""
        cwd = self._vfs_cwd.get(nick, "")
        if pathspec and "::" in pathspec:
            return pathspec  # already fully qualified
        if cwd:
            return cwd + pathspec if pathspec else cwd
        return pathspec

    # ------------------------------------------------------------------
    # LIST
    # ------------------------------------------------------------------

    def _vfs_list(self, nick: str, addr, args: list):
        prefix = self._vfs_resolve(nick, args[0] if args else "")
        from csc_service.server.vfs_data_conn import VFSDataConn

        def _build_listing():
            try:
                vfs = _get_vfs()
                files = vfs.list_dir(prefix) if prefix else vfs.list_dir("")
            except Exception as exc:
                return f"VFS ERR list failed: {exc}\n".encode()
            lines = [f"{f}" for f in sorted(files)]
            lines.append(f"({len(lines)} item(s) at '{prefix or '<root>'}')")
            return "\n".join(lines).encode()

        try:
            conn = VFSDataConn()
            self._vfs_pret(addr, nick, conn.ip, conn.port, "LIST")
            conn.serve_download(_build_listing,
                                on_done=lambda: self._vfs_ok(addr, nick, "LIST done"),
                                on_error=lambda e: self._vfs_err(addr, nick, f"LIST transfer failed: {e}"))
        except Exception as exc:
            self._vfs_err(addr, nick, f"LIST setup failed: {exc}")

    # ------------------------------------------------------------------
    # CWD
    # ------------------------------------------------------------------

    def _vfs_cwd_cmd(self, nick: str, addr, args: list):
        if not args:
            self._vfs_err(addr, nick, "CWD requires a path")
            return
        newpath = args[0].rstrip(":") + "::"  # normalise trailing ::
        self._vfs_cwd[nick] = newpath
        self._vfs_notice(addr, nick, f"VFS CWD {newpath}")

    # ------------------------------------------------------------------
    # ENCRYPT (upload)
    # ------------------------------------------------------------------

    def _vfs_encrypt(self, nick: str, addr, args: list):
        if not args:
            self._vfs_err(addr, nick, "ENCRYPT requires a pathspec")
            return
        pathspec = self._vfs_resolve(nick, args[0])
        requester = self._vfs_requester(nick, addr)

        from csc_service.server.vfs_data_conn import VFSDataConn

        def _on_data(data: bytes):
            try:
                vfs = _get_vfs()
                if vfs.exists(pathspec):
                    vfs.write(pathspec, data, requester)
                else:
                    vfs.create(pathspec, data, mime_type="application/octet-stream",
                               key_hash=None)
                self._vfs_ok(addr, nick, f"ENCRYPT {pathspec} ({len(data)} bytes)")
                self._vfs_trigger_sync()
            except Exception as exc:
                self._vfs_err(addr, nick, f"ENCRYPT write failed: {exc}")

        def _on_error(e: str):
            self._vfs_err(addr, nick, f"ENCRYPT transfer failed: {e}")

        try:
            conn = VFSDataConn()
            self._vfs_pret(addr, nick, conn.ip, conn.port, "ENCRYPT")
            conn.serve_upload(_on_data, _on_error)
        except Exception as exc:
            self._vfs_err(addr, nick, f"ENCRYPT setup failed: {exc}")

    # ------------------------------------------------------------------
    # DECRYPT (download)
    # ------------------------------------------------------------------

    def _vfs_decrypt(self, nick: str, addr, args: list):
        if not args:
            self._vfs_err(addr, nick, "DECRYPT requires a pathspec")
            return
        pathspec = self._vfs_resolve(nick, args[0])
        requester = self._vfs_requester(nick, addr)

        from csc_service.server.vfs_data_conn import VFSDataConn

        def _get_data():
            vfs = _get_vfs()
            if not vfs.exists(pathspec):
                raise FileNotFoundError(f"Not found in VFS: {pathspec}")
            return vfs.read(pathspec, requester)

        try:
            conn = VFSDataConn()
            self._vfs_pret(addr, nick, conn.ip, conn.port, "DECRYPT")
            conn.serve_download(_get_data,
                                on_done=lambda: self._vfs_ok(addr, nick, f"DECRYPT {pathspec}"),
                                on_error=lambda e: self._vfs_err(addr, nick, f"DECRYPT failed: {e}"))
        except Exception as exc:
            self._vfs_err(addr, nick, f"DECRYPT setup failed: {exc}")

    # ------------------------------------------------------------------
    # CAT (inline text, no TCP)
    # ------------------------------------------------------------------

    def _vfs_cat(self, nick: str, addr, args: list):
        if not args:
            self._vfs_err(addr, nick, "CAT requires a pathspec")
            return
        pathspec = self._vfs_resolve(nick, args[0])
        requester = self._vfs_requester(nick, addr)

        def _send():
            try:
                vfs = _get_vfs()
                if not vfs.exists(pathspec):
                    self._vfs_err(addr, nick, f"Not found: {pathspec}")
                    return
                data = vfs.read(pathspec, requester)
                text = data.decode("utf-8", errors="replace")
                for line in text.splitlines():
                    self._vfs_notice(addr, nick, f"VFS CAT {line}")
                self._vfs_notice(addr, nick, "VFS CAT END")
            except Exception as exc:
                self._vfs_err(addr, nick, f"CAT failed: {exc}")

        threading.Thread(target=_send, daemon=True).start()

    # ------------------------------------------------------------------
    # RNFR / RNTO
    # ------------------------------------------------------------------

    def _vfs_rnfr_cmd(self, nick: str, addr, args: list):
        if not args:
            self._vfs_err(addr, nick, "RNFR requires a pathspec")
            return
        self._vfs_rnfr[nick] = self._vfs_resolve(nick, args[0])
        self._vfs_ok(addr, nick, f"RNFR staged: {self._vfs_rnfr[nick]}")

    def _vfs_rnto_cmd(self, nick: str, addr, args: list):
        if not args:
            self._vfs_err(addr, nick, "RNTO requires a pathspec")
            return
        if nick not in self._vfs_rnfr:
            self._vfs_err(addr, nick, "RNTO requires a prior RNFR")
            return
        src = self._vfs_rnfr.pop(nick)
        dst = self._vfs_resolve(nick, args[0])
        try:
            vfs = _get_vfs()
            vfs.rename(src, dst)
            self._vfs_ok(addr, nick, f"RENAMED {src} -> {dst}")
            self._vfs_trigger_sync()
        except Exception as exc:
            self._vfs_err(addr, nick, f"RNTO failed: {exc}")

    # ------------------------------------------------------------------
    # DEL
    # ------------------------------------------------------------------

    def _vfs_del(self, nick: str, addr, args: list):
        if not args:
            self._vfs_err(addr, nick, "DEL requires a pathspec")
            return
        pathspec = self._vfs_resolve(nick, args[0])
        requester = self._vfs_requester(nick, addr)
        try:
            vfs = _get_vfs()
            vfs.delete(pathspec, requester)
            self._vfs_ok(addr, nick, f"DELETED {pathspec}")
            self._vfs_trigger_sync()
        except Exception as exc:
            self._vfs_err(addr, nick, f"DEL failed: {exc}")

    # ------------------------------------------------------------------
    # FTP sync trigger
    # ------------------------------------------------------------------

    def _vfs_trigger_sync(self):
        """Wake the FTP slave's fs watcher so vfs/ block changes propagate via S2S.

        The slave already watches all of serve_root (= csc_root), which includes
        vfs/.  This just signals an immediate delta rather than waiting for the
        next refresh interval — same path ops/ uses.
        """
        try:
            slave = getattr(self.server, "_ftpd_slave", None)
            if slave and hasattr(slave, "schedule_inventory_delta"):
                slave.schedule_inventory_delta()
        except Exception:
            pass
