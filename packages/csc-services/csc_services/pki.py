"""PKI service — IRC command handler for certificate lifecycle.

Oper-only commands for managing TLS certificates used by S2S links.
Requires 'a' or 'A' flag for write operations, 'o' for read-only.

Commands:
    PKI TOKEN <shortname>  — Generate one-time enrollment token
    PKI LIST               — Show all issued certs
    PKI REVOKE <shortname> — Revoke a cert, regenerate CRL
    PKI STATUS             — CA health, CRL age, token count
    PKI PENDING            — Show unused tokens
"""

import json
import os
import re
import secrets
import subprocess
import time
from pathlib import Path

from csc_services import Service

# Shortname must be alphanumeric with dots/hyphens, max 64 chars
_SHORTNAME_RE = re.compile(r"^[a-z0-9][a-z0-9.\-]{0,62}[a-z0-9]$")

# EasyRSA paths
EASYRSA_DIR = Path("/etc/openvpn/easy-rsa")
EASYRSA_BIN = EASYRSA_DIR / "easyrsa"
PKI_DIR = EASYRSA_DIR / "pki"
CA_CRT = PKI_DIR / "ca.crt"
CRL_PEM = PKI_DIR / "crl.pem"
ISSUED_DIR = PKI_DIR / "issued"

# Token storage
TOKEN_FILE = Path("/opt/csc/tmp/csc/run/pki_tokens.json")

# Approved server list (repo-tracked)
APPROVED_FILE = Path("/opt/csc/irc/etc/approved_servers.json")

# PKI log
PKI_LOG = Path("/opt/csc/logs/pki.log")

# Token lifetime: 24 hours
TOKEN_TTL = 86400


def _load_approved():
    """Load approved server list."""
    if APPROVED_FILE.exists():
        try:
            return json.loads(APPROVED_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_approved(approved):
    """Atomically save approved server list."""
    APPROVED_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = APPROVED_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(approved, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, APPROVED_FILE)


def _load_tokens():
    """Load token store from disk."""
    if TOKEN_FILE.exists():
        try:
            return json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_tokens(tokens):
    """Atomically save token store."""
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = TOKEN_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(tokens, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, TOKEN_FILE)


def _write_pki_log(message):
    """Append a timestamped entry to the PKI log."""
    PKI_LOG.parent.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    line = f"{ts} [PKI] {message}\n"
    with open(PKI_LOG, "a", encoding="utf-8") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())


def _prune_expired(tokens):
    """Remove tokens older than TOKEN_TTL."""
    now = time.time()
    expired = [t for t, info in tokens.items()
               if now - info.get("created_at", 0) > TOKEN_TTL]
    for t in expired:
        del tokens[t]
    return len(expired)


class Pki(Service):
    """PKI certificate management service for S2S TLS links."""

    def _require_flag(self, flag_list=("a", "A")):
        """Check if caller has required oper flags. Returns (ok, nick)."""
        # In service context, self.server has caller info
        # The service dispatch provides caller_nick via the command context
        return True  # Flag checking is handled at dispatch layer

    def token(self, shortname=None):
        """Generate a one-time enrollment token for a server.

        Usage: PKI TOKEN <shortname>
        Requires: oper flag 'a' or 'A'
        """
        if not shortname:
            return "Usage: PKI TOKEN <shortname>"

        shortname = shortname.strip().lower()
        if not _SHORTNAME_RE.match(shortname):
            return "Invalid shortname. Use alphanumeric characters, dots, and hyphens only."

        tokens = _load_tokens()
        _prune_expired(tokens)

        # Check if there's already an active token for this shortname
        for tok, info in tokens.items():
            if info.get("shortname") == shortname and not info.get("used"):
                return f"Active token already exists for {shortname}. Use PKI PENDING to view."

        # Generate a cryptographically secure token
        new_token = secrets.token_hex(32)
        tokens[new_token] = {
            "shortname": shortname,
            "created_at": time.time(),
            "used": False,
        }
        _save_tokens(tokens)

        self.log(f"[PKI] Generated enrollment token for {shortname}")
        return f"Enrollment token for {shortname}: {new_token}"

    def list(self):
        """Show all issued certificates.

        Usage: PKI LIST
        Requires: oper flag 'o'
        """
        if not ISSUED_DIR.exists():
            return "No certificates issued (EasyRSA PKI directory not found)"

        certs = []
        for crt_file in sorted(ISSUED_DIR.glob("*.crt")):
            name = crt_file.stem
            try:
                result = subprocess.run(
                    ["openssl", "x509", "-in", str(crt_file),
                     "-noout", "-enddate", "-serial"],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0:
                    lines = result.stdout.strip().split("\n")
                    expiry = ""
                    serial = ""
                    for line in lines:
                        if line.startswith("notAfter="):
                            expiry = line.split("=", 1)[1].strip()
                        elif line.startswith("serial="):
                            serial = line.split("=", 1)[1].strip()
                    # Check revocation status
                    revoked = _is_revoked(serial)
                    status = "REVOKED" if revoked else "valid"
                    certs.append(f"  {name:20s} expires {expiry:30s} [{status}]")
                else:
                    certs.append(f"  {name:20s} (error reading cert)")
            except Exception as e:
                certs.append(f"  {name:20s} (error: {e})")

        if not certs:
            return "No certificates issued"

        header = f"Issued certificates ({len(certs)}):"
        return header + "\n" + "\n".join(certs)

    def revoke(self, shortname=None):
        """Revoke a certificate and regenerate CRL.

        Usage: PKI REVOKE <shortname>
        Requires: oper flag 'a' or 'A'
        """
        if not shortname:
            return "Usage: PKI REVOKE <shortname>"

        shortname = shortname.strip().lower()
        if not _SHORTNAME_RE.match(shortname):
            return "Invalid shortname. Use alphanumeric characters, dots, and hyphens only."

        cert_file = ISSUED_DIR / f"{shortname}.crt"

        if not cert_file.exists():
            return f"No certificate found for {shortname}"

        try:
            # Revoke the certificate
            result = subprocess.run(
                [str(EASYRSA_BIN), "--batch", "revoke", shortname],
                capture_output=True, text=True, timeout=30,
                cwd=str(EASYRSA_DIR),
            )
            if result.returncode != 0:
                return f"Revocation failed: {result.stderr.strip()}"

            # Regenerate CRL
            result = subprocess.run(
                [str(EASYRSA_BIN), "gen-crl"],
                capture_output=True, text=True, timeout=30,
                cwd=str(EASYRSA_DIR),
            )
            if result.returncode != 0:
                return f"CRL regeneration failed: {result.stderr.strip()}"

            # Copy CRL to /etc/csc/
            crl_dest = Path("/etc/csc/crl.pem")
            crl_dest.parent.mkdir(parents=True, exist_ok=True)
            if CRL_PEM.exists():
                import shutil
                shutil.copy2(CRL_PEM, crl_dest)

            _write_pki_log(f"cert revoked: {shortname}    CRL updated and propagated")
            self.log(f"[PKI] Revoked certificate for {shortname}")
            return f"Certificate for {shortname} revoked. CRL updated and propagated."

        except Exception as e:
            return f"Revocation error: {e}"

    def status(self):
        """Show CA health, CRL age, token count, issued cert count.

        Usage: PKI STATUS
        Requires: oper flag 'o'
        """
        lines = []

        # CA certificate
        if CA_CRT.exists():
            lines.append("CA: present")
            try:
                result = subprocess.run(
                    ["openssl", "x509", "-in", str(CA_CRT),
                     "-noout", "-enddate"],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0:
                    expiry = result.stdout.strip().split("=", 1)[-1]
                    lines.append(f"CA expiry: {expiry}")
            except Exception:
                if hasattr(self, 'log'):
                    self.log('Ignored exception', level='DEBUG')
        else:
            lines.append("CA: NOT FOUND")

        # CRL age
        if CRL_PEM.exists():
            mtime = os.path.getmtime(CRL_PEM)
            age_hours = (time.time() - mtime) / 3600
            lines.append(f"CRL age: {age_hours:.1f}h")
        else:
            lines.append("CRL: not generated")

        # Token count
        tokens = _load_tokens()
        _prune_expired(tokens)
        active = sum(1 for t in tokens.values() if not t.get("used"))
        used = sum(1 for t in tokens.values() if t.get("used"))
        lines.append(f"Tokens: {active} active, {used} used")

        # Issued certs count
        if ISSUED_DIR.exists():
            cert_count = len(list(ISSUED_DIR.glob("*.crt")))
            lines.append(f"Issued certs: {cert_count}")
        else:
            lines.append("Issued certs: 0")

        # Approved server count
        approved = _load_approved()
        lines.append(f"Approved servers: {len(approved)}")

        return "\n".join(lines)

    def pending(self):
        """Show tokens issued but not yet used.

        Usage: PKI PENDING
        Requires: oper flag 'o'
        """
        tokens = _load_tokens()
        pruned = _prune_expired(tokens)
        if pruned:
            _save_tokens(tokens)

        pending = [(tok[:16] + "...", info)
                   for tok, info in tokens.items()
                   if not info.get("used")]

        if not pending:
            return "No pending tokens"

        lines = [f"Pending tokens ({len(pending)}):"]
        for tok_short, info in pending:
            shortname = info.get("shortname", "unknown")
            created = time.strftime(
                "%Y-%m-%d %H:%M",
                time.localtime(info.get("created_at", 0)),
            )
            age_h = (time.time() - info.get("created_at", 0)) / 3600
            remaining_h = max(0, (TOKEN_TTL / 3600) - age_h)
            lines.append(
                f"  {tok_short}  {shortname:20s}  created {created}  "
                f"expires in {remaining_h:.1f}h"
            )

        return "\n".join(lines)

    def approve(self, shortname=None):
        """Add a server to the pre-approved enrollment list and push to GitHub.

        Usage: PKI APPROVE <shortname>
        Requires: oper flag 'a' or 'A'
        """
        if not shortname:
            return "Usage: PKI APPROVE <shortname>"

        shortname = shortname.strip().lower()
        if not _SHORTNAME_RE.match(shortname):
            return "Invalid shortname. Use alphanumeric characters, dots, and hyphens only."

        approved = _load_approved()
        if shortname in approved:
            return f"{shortname} is already in the approved list."

        today = time.strftime("%Y-%m-%d")
        approved[shortname] = {"added": today, "note": ""}
        _save_approved(approved)

        # Commit and push so all nodes pick it up via git sync
        try:
            irc_dir = str(APPROVED_FILE.parent.parent)
            subprocess.run(
                ["git", "-C", irc_dir, "add", "etc/approved_servers.json"],
                capture_output=True, text=True, timeout=15,
            )
            subprocess.run(
                ["git", "-C", irc_dir, "commit", "-m", f"pki: approve {shortname}"],
                capture_output=True, text=True, timeout=15,
            )
            result = subprocess.run(
                ["git", "-C", irc_dir, "push"],
                capture_output=True, text=True, timeout=30,
            )
            push_ok = result.returncode == 0
        except Exception as e:
            push_ok = False

        _write_pki_log(f"approved: {shortname}  pushed={push_ok}")
        status = "approved and pushed to GitHub." if push_ok else "approved locally (push failed — run git push manually)."
        return f"{shortname} {status}"

    def remove(self, shortname=None):
        """Remove a server from the pre-approved enrollment list and push to GitHub.

        Usage: PKI REMOVE <shortname>
        Requires: oper flag 'a' or 'A'
        """
        if not shortname:
            return "Usage: PKI REMOVE <shortname>"

        shortname = shortname.strip().lower()
        if not _SHORTNAME_RE.match(shortname):
            return "Invalid shortname."

        approved = _load_approved()
        if shortname not in approved:
            return f"{shortname} is not in the approved list."

        del approved[shortname]
        _save_approved(approved)

        try:
            irc_dir = str(APPROVED_FILE.parent.parent)
            subprocess.run(
                ["git", "-C", irc_dir, "add", "etc/approved_servers.json"],
                capture_output=True, text=True, timeout=15,
            )
            subprocess.run(
                ["git", "-C", irc_dir, "commit", "-m", f"pki: remove {shortname}"],
                capture_output=True, text=True, timeout=15,
            )
            result = subprocess.run(
                ["git", "-C", irc_dir, "push"],
                capture_output=True, text=True, timeout=30,
            )
            push_ok = result.returncode == 0
        except Exception as e:
            push_ok = False

        _write_pki_log(f"removed: {shortname}  pushed={push_ok}")
        status = "removed and pushed to GitHub." if push_ok else "removed locally (push failed — run git push manually)."
        return f"{shortname} {status}"

    def approved(self):
        """List all pre-approved servers.

        Usage: PKI APPROVED
        Requires: oper flag 'o'
        """
        approved = _load_approved()
        if not approved:
            return "No pre-approved servers."

        lines = [f"Pre-approved servers ({len(approved)}):"]
        for name, meta in sorted(approved.items()):
            added = meta.get("added", "unknown")
            note = meta.get("note", "")
            note_str = f"  [{note}]" if note else ""
            lines.append(f"  {name:30s}  added {added}{note_str}")
        return "\n".join(lines)

    def default(self, *args):
        """Default handler — show help."""
        return (
            "PKI commands:\n"
            "  PKI APPROVE <shortname> — Pre-approve a server (no token needed to enroll)\n"
            "  PKI REMOVE <shortname>  — Remove server from approved list\n"
            "  PKI APPROVED            — List pre-approved servers\n"
            "  PKI TOKEN <shortname>   — Generate one-time enrollment token\n"
            "  PKI LIST                — List issued certificates\n"
            "  PKI REVOKE <shortname>  — Revoke a certificate\n"
            "  PKI STATUS              — CA health overview\n"
            "  PKI PENDING             — Show unused tokens"
        )


def _is_revoked(serial):
    """Check if a certificate serial is in the CRL."""
    if not CRL_PEM.exists() or not serial:
        return False
    try:
        result = subprocess.run(
            ["openssl", "crl", "-in", str(CRL_PEM), "-noout", "-text"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            # CRL text output contains revoked serial numbers
            return serial.upper() in result.stdout.upper()
    except Exception:
        import logging
        logging.getLogger(__name__).debug('Ignored exception', exc_info=True)
    return False
