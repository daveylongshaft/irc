"""Utility helpers for the IRC FTP/DCC client surface."""

from __future__ import annotations

import ipaddress
import posixpath
import shlex


def split_command_args(args: str) -> list[str]:
    """Split a local command string, honoring shell-style quotes."""
    if not args:
        return []
    return shlex.split(args)


def normalize_ftp_path(path: str, cwd: str = "/") -> str:
    """Normalize an ftp:/ path or relative FTP path into an absolute VFS path."""
    raw = (path or "").strip()
    if raw.startswith("ftp:"):
        raw = raw[4:]
    if not raw:
        raw = cwd or "/"
    elif not raw.startswith("/"):
        raw = posixpath.join(cwd or "/", raw)
    norm = posixpath.normpath(raw.replace("\\", "/"))
    if not norm.startswith("/"):
        norm = "/" + norm
    return norm


def resolve_ftp_upload_target(local_path: str, ftp_target: str, cwd: str = "/") -> str:
    """Resolve an upload target, appending the source filename if a directory was given."""
    target = normalize_ftp_path(ftp_target, cwd=cwd)
    raw_target = ftp_target[4:] if ftp_target.startswith("ftp:") else ftp_target
    source_name = local_path.replace("\\", "/").rstrip("/").split("/")[-1]
    if ftp_target.endswith("/") or raw_target in (".", "..") or target == "/":
        base = normalize_ftp_path(ftp_target.rstrip("/") or "/", cwd=cwd)
        return normalize_ftp_path(f"{base}/{source_name}", cwd="/")
    return target


def dcc_ip_to_int(ip_str: str) -> int:
    """Encode an IPv4 address as a DCC integer token."""
    return int(ipaddress.IPv4Address(ip_str))


def dcc_int_to_ip(value: str) -> str:
    """Decode a DCC integer token into an IPv4 address."""
    return str(ipaddress.IPv4Address(int(value)))


def parse_dcc_send(ctcp_body: str) -> dict | None:
    """Parse a CTCP DCC SEND payload."""
    if not ctcp_body.startswith("DCC SEND "):
        return None
    parts = shlex.split(ctcp_body)
    if len(parts) < 5 or parts[0] != "DCC" or parts[1] != "SEND":
        return None
    return {
        "filename": parts[2],
        "ip": dcc_int_to_ip(parts[3]),
        "port": int(parts[4]),
        "size": int(parts[5]) if len(parts) > 5 else 0,
    }
