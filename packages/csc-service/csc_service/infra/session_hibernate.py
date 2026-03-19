"""Session hibernation: save/restore volatile server state across restarts."""
import json
import base64
import os
import tempfile
from pathlib import Path

HIBERNATE_FILE = None

def _set_hibernate_path(csc_root):
    """Set the path to the hibernate file."""
    global HIBERNATE_FILE
    HIBERNATE_FILE = Path(csc_root) / "etc" / "session.hibernate.json"

def dump(server):
    """
    Serialize all volatile server state to a hibernation file.

    Serialized state:
    - server.clients: dict with tuple keys -> "host:port" string keys
    - server.encryption_keys: dict with tuple keys -> base64 string values
    - server.nickserv_identified: dict with tuple keys -> string keys
    - server.disconnected_clients: already string keys, no transform
    - server.message_handler.registration_state: tuple keys -> strings
    - server.message_handler._pm_buffer_replayed: set of tuples -> list of strings

    Writes atomically (temp -> fsync -> rename) to prevent partial writes.
    """
    if HIBERNATE_FILE is None:
        return False

    try:
        # Serialize clients dict
        clients_serialized = {}
        for addr, client_info in server.clients.items():
            host, port = addr
            key = f"{host}:{port}"
            # Serialize user_modes set as list
            info_copy = dict(client_info)
            if "user_modes" in info_copy and isinstance(info_copy["user_modes"], set):
                info_copy["user_modes"] = list(info_copy["user_modes"])
            clients_serialized[key] = info_copy

        # Serialize encryption_keys dict (bytes -> base64)
        keys_serialized = {}
        for addr, aes_key in server.encryption_keys.items():
            host, port = addr
            key = f"{host}:{port}"
            if isinstance(aes_key, bytes):
                keys_serialized[key] = base64.b64encode(aes_key).decode('utf-8')
            else:
                keys_serialized[key] = aes_key

        # Serialize nickserv_identified (tuple keys -> strings)
        nickserv_serialized = {}
        for addr, nick in server.nickserv_identified.items():
            host, port = addr
            key = f"{host}:{port}"
            nickserv_serialized[key] = nick

        # Serialize registration_state from message_handler
        registration_serialized = {}
        if hasattr(server.message_handler, 'registration_state'):
            for addr, state_info in server.message_handler.registration_state.items():
                host, port = addr
                key = f"{host}:{port}"
                registration_serialized[key] = state_info

        # Serialize _pm_buffer_replayed from message_handler (set of tuples -> list of strings)
        pm_buffer_serialized = []
        if hasattr(server.message_handler, '_pm_buffer_replayed'):
            for item in server.message_handler._pm_buffer_replayed:
                # Item is a tuple: (sender_addr, recipient_addr, timestamp)
                if isinstance(item, tuple) and len(item) >= 2:
                    sender_addr, recipient_addr = item[0], item[1]
                    sender_host, sender_port = sender_addr
                    recip_host, recip_port = recipient_addr
                    key = f"{sender_host}:{sender_port}:{recip_host}:{recip_port}"
                    pm_buffer_serialized.append(key)

        # Build hibernation data
        hibernation_data = {
            "clients": clients_serialized,
            "encryption_keys": keys_serialized,
            "nickserv_identified": nickserv_serialized,
            "disconnected_clients": server.disconnected_clients,
            "registration_state": registration_serialized,
            "pm_buffer_replayed": pm_buffer_serialized,
        }

        # Write atomically: temp -> fsync -> rename
        HIBERNATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        temp_path = Path(tempfile.mktemp(dir=HIBERNATE_FILE.parent, prefix=".hibernate."))

        with open(temp_path, 'w', encoding='utf-8') as f:
            f.write(json.dumps(hibernation_data, indent=2))
            # Fsync to guarantee durability
            os.fsync(f.fileno())

        # Atomic rename
        temp_path.replace(HIBERNATE_FILE)

        return True
    except Exception as e:
        print(f"[hibernate] dump failed: {e}")
        return False

def restore_if_exists(server):
    """
    Restore volatile server state from hibernation file if it exists.

    Returns True if restoration was successful, False otherwise.
    Deletes the hibernation file immediately after successful restore.
    """
    if HIBERNATE_FILE is None or not HIBERNATE_FILE.exists():
        return False

    try:
        hibernation_data = json.loads(HIBERNATE_FILE.read_text(encoding='utf-8'))

        # Restore clients (deserialize "host:port" keys back to tuples)
        for key_str, client_info in hibernation_data.get("clients", {}).items():
            host, port = key_str.rsplit(":", 1)
            port = int(port)
            addr = (host, port)
            # Restore user_modes from list to set
            if "user_modes" in client_info and isinstance(client_info["user_modes"], list):
                client_info["user_modes"] = set(client_info["user_modes"])
            server.clients[addr] = client_info

        # Restore encryption_keys (deserialize base64 back to bytes)
        for key_str, aes_key_b64 in hibernation_data.get("encryption_keys", {}).items():
            host, port = key_str.rsplit(":", 1)
            port = int(port)
            addr = (host, port)
            try:
                server.encryption_keys[addr] = base64.b64decode(aes_key_b64)
            except Exception:
                server.encryption_keys[addr] = aes_key_b64

        # Restore nickserv_identified (deserialize strings back to tuple keys)
        for key_str, nick in hibernation_data.get("nickserv_identified", {}).items():
            host, port = key_str.rsplit(":", 1)
            port = int(port)
            addr = (host, port)
            server.nickserv_identified[addr] = nick

        # Restore disconnected_clients (already string keys)
        server.disconnected_clients.update(hibernation_data.get("disconnected_clients", {}))

        # Restore registration_state in message_handler
        if hasattr(server.message_handler, 'registration_state'):
            for key_str, state_info in hibernation_data.get("registration_state", {}).items():
                host, port = key_str.rsplit(":", 1)
                port = int(port)
                addr = (host, port)
                server.message_handler.registration_state[addr] = state_info

        # Restore _pm_buffer_replayed in message_handler
        if hasattr(server.message_handler, '_pm_buffer_replayed'):
            for key_str in hibernation_data.get("pm_buffer_replayed", []):
                parts = key_str.rsplit(":", 3)
                if len(parts) == 4:
                    sender_host, sender_port, recip_host, recip_port = parts
                    sender_addr = (sender_host, int(sender_port))
                    recip_addr = (recip_host, int(recip_port))
                    # Reconstruct tuple (without timestamp, can be regenerated)
                    server.message_handler._pm_buffer_replayed.add((sender_addr, recip_addr))

        # Delete hibernation file after successful restore
        HIBERNATE_FILE.unlink()

        return True
    except Exception as e:
        print(f"[hibernate] restore failed: {e}")
        return False

def exists():
    """Check if hibernation file exists."""
    if HIBERNATE_FILE is None:
        return False
    return HIBERNATE_FILE.exists()
