"""
NickServ Service - User registration and identity management.

Commands:
  REGISTER <email> <password> - Register the current nick
  IDENT <password>             - Identify with your registered nick
  UNREGISTER <nick>            - (Oper only) Unregister a nick
  INFO <nick>                  - Show registration info (visible to oper/self)

Data storage:
  - nickserv.db: flat text file with format: nick:pass_hash:email:timestamp
"""

import hashlib
import time
import os
from csc_service.server.service import Service


class Nickserv(Service):
    """
    NickServ service for user registration and authentication.

    Stores registration data in a flat text file (nickserv.db) with format:
    nick:pass_hash:email:registered_timestamp
    """

    def __init__(self, server_instance):
        """Initialize the NickServ service."""
        super().__init__(server_instance)
        self.name = "nickserv"
        self.init_data()

        # Initialize the registration database file path
        self.db_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "server",
            "nickserv.db"
        )

        # In-memory cache of registered nicks for fast lookups
        self._registry = {}
        self._load_db()

        self.log(f"NickServ service initialized. DB file: {self.db_file}")

    def _load_db(self):
        """Load the nickserv database from disk into memory."""
        self._registry = {}
        if not os.path.exists(self.db_file):
            self.log(f"NickServ DB does not exist yet: {self.db_file}")
            return

        try:
            with open(self.db_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    parts = line.split(':')
                    if len(parts) >= 4:
                        nick, pass_hash, email, timestamp = parts[0], parts[1], parts[2], parts[3]
                        self._registry[nick.lower()] = {
                            'nick': nick,
                            'pass_hash': pass_hash,
                            'email': email,
                            'registered_timestamp': float(timestamp)
                        }
            self.log(f"Loaded {len(self._registry)} registered nicks from nickserv.db")
        except Exception as e:
            self.log(f"Error loading NickServ DB: {e}")

    def _save_db(self):
        """Save the in-memory registry back to disk."""
        try:
            os.makedirs(os.path.dirname(self.db_file), exist_ok=True)
            with open(self.db_file, 'w', encoding='utf-8') as f:
                for nick_lower, data in sorted(self._registry.items()):
                    line = f"{data['nick']}:{data['pass_hash']}:{data['email']}:{data['registered_timestamp']}\n"
                    f.write(line)
            self.log(f"Saved {len(self._registry)} registered nicks to nickserv.db")
        except Exception as e:
            self.log(f"Error saving NickServ DB: {e}")

    def _hash_password(self, password: str) -> str:
        """Hash a password using MD5."""
        return hashlib.md5(password.encode('utf-8')).hexdigest()

    def _verify_password(self, stored_hash: str, password: str) -> bool:
        """Verify a password against its stored hash."""
        return self._hash_password(password) == stored_hash

    def register(self, email: str, password: str) -> str:
        """
        Register the current nick with an email and password.

        Format: /msg NickServ REGISTER <email> <password>

        Returns:
            Success or error message
        """
        if not email or not password:
            return "Error: REGISTER requires email and password. Usage: REGISTER <email> <password>"

        # Note: The nick is determined by the client connection
        # The service doesn't have direct access to the calling nick,
        # so we'll need to integrate this with the message handler.
        # For now, return a message indicating this needs integration.
        return "Error: NickServ REGISTER must be called via PRIVMSG from the IRC server integration."

    def _register_nick(self, nick: str, email: str, password: str) -> str:
        """
        Internal method to register a nick.
        Called from the server message handler.
        """
        nick_lower = nick.lower()

        # Check if already registered
        if nick_lower in self._registry:
            return f"Error: Nick '{nick}' is already registered."

        # Create registration record
        pass_hash = self._hash_password(password)
        timestamp = time.time()

        self._registry[nick_lower] = {
            'nick': nick,
            'pass_hash': pass_hash,
            'email': email,
            'registered_timestamp': timestamp
        }

        self._save_db()
        self.log(f"Registered nick: {nick} with email: {email}")
        return f"Nick '{nick}' has been registered successfully."

    def ident(self, password: str) -> str:
        """
        Identify with your registered nick using the password.

        Returns:
            Success or error message
        """
        if not password:
            return "Error: IDENT requires a password. Usage: IDENT <password>"

        # Similar to register, this needs server integration
        return "Error: NickServ IDENT must be called via PRIVMSG from the IRC server integration."

    def _ident_nick(self, nick: str, password: str) -> tuple:
        """
        Internal method to identify a nick.
        Returns: (success: bool, message: str)
        """
        nick_lower = nick.lower()

        # Check if nick is registered
        if nick_lower not in self._registry:
            return (False, f"Error: Nick '{nick}' is not registered.")

        # Verify password
        record = self._registry[nick_lower]
        if not self._verify_password(record['pass_hash'], password):
            return (False, "Error: Password is incorrect.")

        self.log(f"Nick {nick} identified successfully.")
        return (True, f"You have identified successfully as {nick}.")

    def unregister(self, nick: str) -> str:
        """
        Unregister a nick (oper only).

        Returns:
            Success or error message
        """
        if not nick:
            return "Error: UNREGISTER requires a nick. Usage: UNREGISTER <nick>"

        nick_lower = nick.lower()

        # Check if registered
        if nick_lower not in self._registry:
            return f"Error: Nick '{nick}' is not registered."

        # Remove the registration
        del self._registry[nick_lower]
        self._save_db()

        self.log(f"Unregistered nick: {nick}")
        return f"Nick '{nick}' has been unregistered."

    def info(self, nick: str) -> str:
        """
        Show registration information for a nick (visible to oper/self).

        Returns:
            Info or error message
        """
        if not nick:
            return "Error: INFO requires a nick. Usage: INFO <nick>"

        nick_lower = nick.lower()

        # Check if registered
        if nick_lower not in self._registry:
            return f"Error: Nick '{nick}' is not registered."

        record = self._registry[nick_lower]
        timestamp = record['registered_timestamp']
        reg_time = time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(timestamp))

        # Return public info (hide password hash)
        return f"Nick: {record['nick']}\nEmail: {record['email']}\nRegistered: {reg_time}"

    def is_registered(self, nick: str) -> bool:
        """Check if a nick is registered."""
        return nick.lower() in self._registry

    def default(self, *args) -> str:
        """Show available NickServ commands."""
        return (
            "NickServ - User Registration Service\n"
            "Available commands:\n"
            "  /msg NickServ REGISTER <email> <password>  - Register your nick\n"
            "  /msg NickServ IDENT <password>             - Identify with your nick\n"
            "  /msg NickServ UNREGISTER <nick>            - (Oper) Unregister a nick\n"
            "  /msg NickServ INFO <nick>                  - Show nick info"
        )
