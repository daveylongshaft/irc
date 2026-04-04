import os
import json
import subprocess
import time
from pathlib import Path
from csc_services import Service
from csc_server_core.irc import format_irc_message, SERVER_NAME

class CryptServ(Service):
    """
    CryptServ is a key distribution bot, managing RSA key pairs for channels and DM pairs.
    It acts as a Certificate Authority, issuing keys and responding to client requests.
    """
    
    CERTS_DIR_NAME = "certs"
    SCRIPT_DIR_NAME = "scripts"
    GENCERT_SCRIPT = "gencert.sh"
    DATA_FILE = "cryptserv_data.json"

    def __init__(self, server_instance):
        super().__init__(server_instance)
        self.name = "cryptserv"
        self.init_data(self.DATA_FILE)
        
        # Ensure certs directory exists
        self.certs_dir = Path(self.server.project_root_dir) / self.CERTS_DIR_NAME
        self.certs_dir.mkdir(parents=True, exist_ok=True)
        
        # Path to gencert.sh
        self.gencert_path = Path(self.server.project_root_dir) / self.SCRIPT_DIR_NAME / self.GENCERT_SCRIPT
        
        # Store issued certificates metadata {target: {private_path, public_path, issued_at}}
        if not self.get_data("issued_certs"):
            self.put_data("issued_certs", {})
        
        self.server.log(f"[CryptServ] Initialized. Certs Dir: {self.certs_dir}")

    def _run_gencert_script(self, target_name):
        """Executes the gencert.sh script to generate keys for a target."""
        if not self.gencert_path.exists():
            self.server.log(f"[CryptServ ERROR] gencert.sh not found at {self.gencert_path}")
            return False, f"Error: Certificate generation script not found."

        try:
            # Use wsl bash for execution on Windows
            cmd = ["wsl", "bash", str(self.gencert_path), target_name]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            self.server.log(f"[CryptServ] gencert.sh output: {result.stdout.strip()}")
            if result.stderr:
                self.server.log(f"[CryptServ WARNING] gencert.sh stderr: {result.stderr.strip()}")
            return True, "Certificate generated successfully."
        except subprocess.CalledProcessError as e:
            self.server.log(f"[CryptServ ERROR] gencert.sh failed for {target_name}: {e.stderr}")
            return False, f"Error: Certificate generation failed for {target_name}: {e.stderr.strip()}"
        except Exception as e:
            self.server.log(f"[CryptServ ERROR] Unexpected error running gencert.sh: {e}")
            return False, f"Error: Unexpected script error."

    def _load_cert_bundle(self, target_name):
        """Loads private and public keys for a given target."""
        target_dir = self.certs_dir / target_name
        private_key_path = target_dir / "private.pem"
        public_key_path = target_dir / "public.pem"
        
        if not private_key_path.exists() or not public_key_path.exists():
            return None
            
        with open(private_key_path, "r") as f:
            private_key = f.read()
        with open(public_key_path, "r") as f:
            public_key = f.read()
            
        return {"private": private_key, "public": public_key}

    def request(self, target: str, requestor_nick: str) -> str:
        """
        Handles requests for certificates (channel or DM).
        Args:
            target: The channel name (e.g. #general) or sorted DM pair (e.g. alice:bob).
            requestor_nick: The nick of the client requesting the certificate.
        """
        self.server.log(f"[CryptServ] Request for '{target}' from '{requestor_nick}'")
        
        issued_certs = self.get_data("issued_certs")
        
        # Check if cert already exists
        if target in issued_certs:
            cert_bundle = self._load_cert_bundle(target)
            if cert_bundle:
                self.server.log(f"[CryptServ] Cert for '{target}' already exists.")
                return self._send_cert_bundle_to_requestor(cert_bundle, target, requestor_nick)

        # Generate new cert
        success, msg = self._run_gencert_script(target)
        if not success:
            return f"Error issuing certificate for {target}: {msg}"
            
        cert_bundle = self._load_cert_bundle(target)
        if not cert_bundle:
            return f"Error: Failed to load generated certificate for {target}."

        issued_certs[target] = {
            "issued_at": time.time(),
            "private_path": str((self.certs_dir / target / "private.pem").relative_to(self.server.project_root_dir)),
            "public_path": str((self.certs_dir / target / "public.pem").relative_to(self.server.project_root_dir)),
        }
        self.put_data("issued_certs", issued_certs)
        self.server.log(f"[CryptServ] Issued new cert for '{target}'.")
        
        return self._send_cert_bundle_to_requestor(cert_bundle, target, requestor_nick)

    def _send_cert_bundle_to_requestor(self, cert_bundle: dict, target: str, requestor_nick: str) -> str:
        """Sends the certificate bundle as PRIVMSG to the requestor."""
        # This will be sent as a series of PRIVMSGs to the requestor, encrypted by DH-AES.
        # Format: CRYPTSERV CERT <target> :<json_bundle>
        bundle_json = json.dumps(cert_bundle)
        
        # Find requestor's address
        requestor_addr = None
        for addr, client_info in self.server.clients.items():
            if client_info.get("name") == requestor_nick:
                requestor_addr = addr
                break
                
        if not requestor_addr:
            return f"Error: Requestor '{requestor_nick}' not found to send cert bundle."

        # Use the server's message handler to send the PRIVMSG to the requestor.
        # This will get encrypted by the server's DH-AES.
        
        # Private key is sensitive, should not be broadcasted.
        # Send private key directly to requestor in a separate, secure message.
        self.server.send_privmsg_to_client(requestor_addr, self.name, requestor_nick, f"CRYPT_PRIVATE {target} :{cert_bundle['private']}")
        self.server.send_privmsg_to_client(requestor_addr, self.name, requestor_nick, f"CRYPT_PUBLIC {target} :{cert_bundle['public']}")
        
        self.server.log(f"[CryptServ] Sent cert bundle for '{target}' to '{requestor_nick}'.")
        return f"Certificate for '{target}' sent to {requestor_nick}."
        
    def default(self, *args) -> str:
        """Default handler for CryptServ commands."""
        return "CryptServ commands: REQUEST <target>"

