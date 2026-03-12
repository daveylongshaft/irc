"""PKI CLI commands: enroll, cert status.

csc-ctl enroll <ca_url> <token>  — Enroll this server for a TLS certificate
csc-ctl cert status              — Show local certificate status
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path


from csc_service.shared.platform import Platform

def _get_openssl_cmd():
    """Return path to openssl executable."""
    import shutil
    cmd = shutil.which("openssl")
    if cmd:
        return cmd
    # Common Windows locations
    if os.name == 'nt':
        candidates = [
            r"C:\Program Files\Git\usr\bin\openssl.exe",
            r"C:\Program Files\OpenSSL-Win64\bin\openssl.exe",
        ]
        for c in candidates:
            if os.path.exists(c):
                return c
    return "openssl"  # Fallback to PATH


def _get_server_shortname():
    """Read the server shortname from server_name file or hostname."""
    sn_file = Platform.PROJECT_ROOT / "server_name"
    if sn_file.exists():
        name = sn_file.read_text(encoding="utf-8").strip()
        if name:
            return name
    # Fallback to hostname
    import socket
    return socket.gethostname().split(".")[0]


def _generate_key_and_csr(shortname):
    """Generate a private key and CSR using openssl subprocess.

    Returns (key_pem, csr_pem) as strings.
    """
    # Bypass Platform() object to avoid access violation crash on exit
    csc_root = Path(os.environ.get("CSC_ROOT", "C:/csc"))
    tmp_dir = csc_root / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    
    key_path = tmp_dir / f"{shortname}.key"
    csr_path = tmp_dir / f"{shortname}.csr"
    openssl = _get_openssl_cmd()
    
    try:
        # Generate private key
        result = subprocess.run(
            [openssl, "genrsa", "-out", str(key_path), "4096"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Key generation failed: {result.stderr.strip()}")

        # Generate CSR
        result = subprocess.run(
            [
                openssl, "req", "-new",
                "-key", str(key_path),
                "-out", str(csr_path),
                "-subj", f"/CN={shortname}",
            ],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"CSR generation failed: {result.stderr.strip()}")

        key_pem = key_path.read_text(encoding="utf-8")
        csr_pem = csr_path.read_text(encoding="utf-8")

        return key_pem, csr_pem

    finally:
        for p in (key_path, csr_path):
            try:
                if p.exists():
                    p.unlink()
            except OSError:
                pass


def enroll(args, config_manager):
    """Enroll this server for a TLS certificate.

    1. Gets server shortname from server_name file
    2. Generates private key + CSR
    3. POSTs to enrollment endpoint
    4. Saves key and chain to etc/
    """
    try:
        ca_url = args.ca_url.rstrip("/")
        token = getattr(args, "token", None) or ""

        shortname = _get_server_shortname()
        print(f"Enrolling as: {shortname}")

        # Generate key and CSR
        print("Generating private key and CSR...")
        try:
            key_pem, csr_pem = _generate_key_and_csr(shortname)
        except RuntimeError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"Unexpected key gen error: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            sys.exit(1)

        # POST to enrollment endpoint
        mode = "token" if token else "pre-approved"
        print(f"Requesting certificate from {ca_url}/enroll [{mode}] ...")
        try:
            import urllib.request
            import urllib.error

            payload_dict = {"shortname": shortname, "csr_pem": csr_pem}
            if token:
                payload_dict["token"] = token
            payload = json.dumps(payload_dict).encode("utf-8")

            req = urllib.request.Request(
                f"{ca_url}/enroll",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            print("DEBUG: Sending POST request...")
            with urllib.request.urlopen(req, timeout=30) as resp:
                resp_data = json.loads(resp.read().decode("utf-8"))
            print("DEBUG: Response received.")

        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            try:
                resp_json = json.loads(body)
                err = resp_json.get("error", body)
                hint = resp_json.get("hint", "")
            except json.JSONDecodeError:
                err = body
                hint = ""
            print(f"Enrollment failed ({e.code}): {err}", file=sys.stderr)
            if hint:
                print(f"  Hint: {hint}", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"Enrollment failed during communication: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            sys.exit(1)

        if resp_data.get("status") != "ok":
            print(f"Enrollment failed: {resp_data}", file=sys.stderr)
            sys.exit(1)

        chain_pem = resp_data["chain_pem"]

        # Save private key
        etc_dir = Platform.get_etc_dir()
        key_file = etc_dir / f"{shortname}.key"
        print(f"Saving key to {key_file}...")
        key_file.write_text(key_pem, encoding="utf-8")
        try:
            os.chmod(key_file, 0o600)
        except Exception:
            pass # Windows chmod is limited

        # Save certificate chain
        chain_file = etc_dir / f"{shortname}.chain.pem"
        print(f"Saving chain to {chain_file}...")
        chain_file.write_text(chain_pem, encoding="utf-8")
        try:
            os.chmod(chain_file, 0o644)
        except Exception:
            pass

        print(f"Certificate enrolled successfully!")
        print(f"  Key:   {key_file}")
        print(f"  Chain: {chain_file}")
        print(f"  Valid: {resp_data.get('valid_from')} -> {resp_data.get('valid_to')}")

    except Exception as e:
        print(f"FATAL ERROR in enroll: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)

    print(f"Certificate enrolled successfully!")
    print(f"  Key:   {key_file}")
    print(f"  Chain: {chain_file}")
    print(f"  Valid: {resp_data.get('valid_from')} -> {resp_data.get('valid_to')}")


def cert_status(args, config_manager):
    """Show local certificate status.

    Reads the local certificate chain and displays:
    - CN, serial, not-before, not-after, days remaining
    - Revocation status against local CRL
    """
    shortname = _get_server_shortname()
    etc_dir = Platform.get_etc_dir()
    chain_file = etc_dir / f"{shortname}.chain.pem"
    openssl = _get_openssl_cmd()

    if not chain_file.exists():
        print(f"No certificate found for {shortname}")
        print(f"  Expected: {chain_file}")
        print("  To obtain a certificate:")
        print("    csc-ctl enroll https://facingaddictionwithhope.com/csc/pki/")
        print("  If this server is not yet pre-approved, ask an oper to run:")
        print(f"    PKI APPROVE {shortname}")
        sys.exit(1)

    # Parse certificate details
    try:
        result = subprocess.run(
            [
                openssl, "x509", "-in", str(chain_file),
                "-noout", "-subject", "-serial", "-dates",
            ],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            print(f"Error reading certificate: {result.stderr.strip()}")
            sys.exit(1)

        info = {}
        for line in result.stdout.strip().split("\n"):
            if "=" in line:
                key, val = line.split("=", 1)
                info[key.strip()] = val.strip()

        cn = info.get("subject", "").replace("CN = ", "").replace("CN=", "")
        serial = info.get("serial", "unknown")
        not_before = info.get("notBefore", "unknown")
        not_after = info.get("notAfter", "unknown")

        # Calculate days remaining
        days_remaining = "unknown"
        try:
            result2 = subprocess.run(
                [
                    openssl, "x509", "-in", str(chain_file),
                    "-noout", "-checkend", "0",
                ],
                capture_output=True, text=True, timeout=10,
            )
            if result2.returncode != 0:
                days_remaining = "EXPIRED"
            else:
                # Calculate from not_after
                result3 = subprocess.run(
                    [
                        openssl, "x509", "-in", str(chain_file),
                        "-noout", "-enddate",
                    ],
                    capture_output=True, text=True, timeout=10,
                )
                if result3.returncode == 0:
                    end_str = result3.stdout.strip().split("=", 1)[-1]
                    # Parse openssl date format
                    from email.utils import parsedate_to_datetime
                    try:
                        end_dt = parsedate_to_datetime(end_str)
                        import datetime
                        remaining = end_dt - datetime.datetime.now(
                            datetime.timezone.utc
                        )
                        days_remaining = f"{remaining.days} days"
                    except Exception:
                        days_remaining = "unknown"
        except Exception:
            pass

        # Check revocation status
        crl_file = etc_dir / "crl.pem"
        revoked = False
        if crl_file.exists() and serial != "unknown":
            try:
                result4 = subprocess.run(
                    [openssl, "crl", "-in", str(crl_file), "-noout", "-text"],
                    capture_output=True, text=True, timeout=10,
                )
                if result4.returncode == 0:
                    revoked = serial.upper() in result4.stdout.upper()
            except Exception:
                pass

        print(f"Certificate Status for {shortname}")
        print(f"  CN:          {cn}")
        print(f"  Serial:      {serial}")
        print(f"  Not Before:  {not_before}")
        print(f"  Not After:   {not_after}")
        print(f"  Remaining:   {days_remaining}")
        print(f"  Status:      {'REVOKED' if revoked else 'Valid'}")
        print(f"  Chain file:  {chain_file}")

    except Exception as e:
        print(f"Error checking certificate: {e}")
        sys.exit(1)
