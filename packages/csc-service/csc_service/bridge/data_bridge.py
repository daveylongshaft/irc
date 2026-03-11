"""
Data persistence for the Bridge Daemon.

Handles storage of user accounts, connection history, and favorites.
"""

from csc_service.shared.data import Data
from typing import Dict, List, Optional
import hashlib
import os

class BridgeData(Data):
    """
    - What it does: Manages persistent storage for the Bridge Daemon, including
        user accounts, connection history, and favorites. Extends csc_shared.data.Data.
    - Arguments: None (inherits from Data)
    - Returns: N/A (class definition)

    Structure:
    {
      "users": {
        "username": {
          "password_hash": "...",
          "salt": "...",
          "history": [ "connection_string", ... ],
          "favorites": { "alias": "connection_string" },
          "settings": { "default_nick": "..." }
        }
      }
    }
    """

    def __init__(self):
        """
        Initializes BridgeData by loading bridge_data.json and ensuring the "users" key exists.

        Args:
            None

        Returns:
            None

        Raises:
            IOError: If bridge_data.json cannot be read or created.
            JSONDecodeError: If bridge_data.json contains invalid JSON.

        Data:
            Reads/Writes: bridge_data.json via parent Data class methods.
            Writes: self.data["users"] = {} if not present.

        Side effects:
            - Disk I/O: Loads or creates bridge_data.json in the configured data directory.
            - Initializes persistent storage for user accounts.

        Thread safety:
            Not thread-safe. Parent Data class uses file-based locking but this init
            should be called once during daemon startup before concurrent access begins.

        Children:
            - super().__init__(): Initializes parent Data class.
            - self.init_data("bridge_data.json"): Loads or creates the JSON file.
            - self.get_data("users"): Retrieves the users dictionary.
            - self.put_data("users", {}): Writes empty users dict if not present.

        Parents:
            - BridgeData class constructor (called when instantiating BridgeData).
            - Bridge daemon initialization code.
        """
        super().__init__()
        self.init_data("bridge_data.json")
        if not self.get_data("users"):
            self.put_data("users", {})

    def create_user(self, username, password):
        """
        Creates a new user account with salted password hash, empty history, favorites, and settings.

        Args:
            username (str): The username for the new account. Must be unique.
                Valid values: Any non-empty string. No length constraints enforced.
            password (str): The plaintext password to hash and store.
                Valid values: Any string (empty passwords allowed but discouraged).

        Returns:
            bool: True if user created successfully, False if username already exists.

        Raises:
            None (exceptions from underlying storage methods may propagate).

        Data:
            Reads: self.data["users"] - dictionary mapping usernames to user objects.
            Writes: self.data["users"][username] - creates new user entry with structure:
                {
                    "password_hash": str (64-char hex SHA256 digest),
                    "salt": str (32-char hex, 16 random bytes),
                    "history": [] (empty list),
                    "favorites": {} (empty dict),
                    "settings": {} (empty dict)
                }
            Mutates: Appends to users dictionary and persists to disk.

        Side effects:
            - Disk I/O: Writes updated users dictionary to bridge_data.json.
            - Crypto: Generates 16 random bytes via os.urandom for salt.

        Thread safety:
            Not thread-safe. Concurrent calls may result in race conditions.
            Parent Data class provides file locking for individual put_data operations
            but not for the read-modify-write sequence here.

        Children:
            - os.urandom(16): Generates cryptographic random bytes for salt.
            - self._hash_password(password, salt): Computes SHA256 hash.
            - self.get_data("users"): Retrieves users dictionary.
            - self.put_data("users", users): Persists updated users dictionary.

        Parents:
            - ControlHandler._try_auth(): Auto-creates "admin" user if DB is empty.
            - Setup/bootstrap scripts for daemon initialization.
            - Admin tools for user management.
        """
        users = self.get_data("users")
        if username in users:
            return False
        
        salt = os.urandom(16).hex()
        pwd_hash = self._hash_password(password, salt)
        
        users[username] = {
            "password_hash": pwd_hash,
            "salt": salt,
            "history": [],
            "favorites": {},
            "settings": {}
        }
        self.put_data("users", users)
        return True

    def validate_user(self, username, password):
        """
        Validates user credentials by comparing the provided password's salted hash against the stored hash.

        Args:
            username (str): The username to authenticate.
                Valid values: Any string. Non-existent usernames return False.
            password (str): The plaintext password to verify.
                Valid values: Any string.

        Returns:
            bool: True if username exists and password hash matches, False otherwise.
                Specifically returns False if:
                - Username does not exist in users dictionary.
                - Password hash does not match stored hash.

        Raises:
            None (safe to call with any input, returns False on errors).

        Data:
            Reads: self.data["users"] - retrieves user entry if exists.
            Reads: self.data["users"][username]["salt"] - retrieves stored salt.
            Reads: self.data["users"][username]["password_hash"] - retrieves stored hash.
            Does not mutate any data.

        Side effects:
            None (read-only operation, no I/O beyond memory access).

        Thread safety:
            Thread-safe for reads. Multiple concurrent validations are safe.
            Parent Data class holds data in memory after initial load.

        Children:
            - self.get_data("users"): Retrieves users dictionary.
            - self._hash_password(password, salt): Computes hash for comparison.

        Parents:
            - ControlHandler._try_auth(): Validates credentials during lobby authentication.
            - API endpoints for user authentication.
        """
        users = self.get_data("users")
        user_data = users.get(username)
        if not user_data:
            return False
            
        salt = user_data["salt"]
        expected_hash = user_data["password_hash"]
        
        return self._hash_password(password, salt) == expected_hash

    def add_history(self, username, conn_str):
        """
        Adds a connection string to the user's history list, moving it to the top if already present.

        Args:
            username (str): The username whose history to update.
                Valid values: Any string. Non-existent usernames are silently ignored.
            conn_str (str): The connection string to add to history.
                Format: "proto:enc:dialect:host:port" (e.g., "tcp:none:rfc:irc.example.com:6667").
                Valid values: Any string (validation not enforced here).

        Returns:
            None

        Raises:
            None (exceptions from underlying storage methods may propagate).

        Data:
            Reads: self.data["users"] - to check username exists.
            Reads: self.data["users"][username]["history"] - list of connection strings.
            Writes: self.data["users"][username]["history"] - updated list with conn_str at index 0.
            Mutates: Modifies history list in-place (removes duplicates, inserts at front, truncates to 25).
                Shape: List[str] with max length 25.

        Side effects:
            - Disk I/O: Writes updated users dictionary to bridge_data.json.
            - List modification: Removes existing conn_str if present, inserts at index 0, caps at 25 items.

        Thread safety:
            Not thread-safe. Concurrent modifications to the same user's history may result in
            race conditions or lost updates. Parent Data class provides file locking for writes
            but not for the read-modify-write sequence.

        Children:
            - self.get_data("users"): Retrieves users dictionary.
            - list.remove(conn_str): Removes existing entry if present.
            - list.insert(0, conn_str): Adds conn_str to front of list.
            - self.put_data("users", users): Persists updated users dictionary.

        Parents:
            - ControlHandler._do_connect(): Saves connection string to history after successful connect.
            - Connection management code tracking recent connections.
        """
        users = self.get_data("users")
        if username not in users: return
        
        history = users[username]["history"]
        
        # Remove existing if present to move to top
        if conn_str in history:
            history.remove(conn_str)
            
        history.insert(0, conn_str)
        users[username]["history"] = history[:25]
        self.put_data("users", users)

    def get_history(self, username) -> List[str]:
        """
        Retrieve the connection history for a user.

        Args:
            username (str): The username to look up. Case-sensitive.
                If the user does not exist, returns an empty list.

        Returns:
            List[str]: Connection strings in reverse chronological order
                (most recent first), max 25 entries. Empty list if user
                not found or has no history.

        Raises:
            None. Missing users return empty list silently.

        Data:
            Reads self._data["users"] (dict[str, dict]) via get_data("users").
            Does not mutate any state.

        Side effects:
            Disk read via get_data() to load users JSON.

        Children:
            self.get_data("users")

        Parents:
            Called by ControlHandler._handle_command() for /trans history.
        """
        users = self.get_data("users")
        return users.get(username, {}).get("history", [])

    def set_favorite(self, username, alias, conn_str):
        """
        Stores a connection string under an alias in the user's favorites dictionary.

        Args:
            username (str): The username whose favorites to update.
                Valid values: Any string. Non-existent usernames are silently ignored.
            alias (str): The alias/shortcut name for this connection.
                Valid values: Any string. Overwrites existing alias if present.
                Constraints: No length or character restrictions enforced.
            conn_str (str): The connection string to store.
                Format: "proto:enc:dialect:host:port" (e.g., "udp:rsa:csc:127.0.0.1:9525").
                Valid values: Any string (validation not enforced here).

        Returns:
            None

        Raises:
            None (exceptions from underlying storage methods may propagate).

        Data:
            Reads: self.data["users"] - to check username exists.
            Reads: self.data["users"][username]["favorites"] - dictionary of aliases to conn_strs.
            Writes: self.data["users"][username]["favorites"][alias] = conn_str.
            Mutates: Adds or updates alias in favorites dictionary.
                Shape: Dict[str, str] mapping alias names to connection strings.

        Side effects:
            - Disk I/O: Writes updated users dictionary to bridge_data.json.
            - Dictionary modification: Overwrites existing alias if present.

        Thread safety:
            Not thread-safe. Concurrent modifications to the same user's favorites may result in
            race conditions. Parent Data class provides file locking for writes but not for the
            read-modify-write sequence.

        Children:
            - self.get_data("users"): Retrieves users dictionary.
            - self.put_data("users", users): Persists updated users dictionary.

        Parents:
            - Admin/management commands for saving favorite connections.
            - User preference management tools.
        """
        users = self.get_data("users")
        if username not in users: return
        users[username]["favorites"][alias] = conn_str
        self.put_data("users", users)

    def get_favorite(self, username, alias) -> Optional[str]:
        """
        Retrieves a connection string from the user's favorites by alias.

        Args:
            username (str): The username whose favorites to query.
                Valid values: Any string. Non-existent usernames return None.
            alias (str): The alias to look up.
                Valid values: Any string. Non-existent aliases return None.

        Returns:
            Optional[str]: The connection string if found, None otherwise.
                - Returns None if username does not exist.
                - Returns None if user exists but alias not in favorites.
                - Returns str (connection string) if both username and alias exist.

        Raises:
            None (safe to call with any input, returns None on errors).

        Data:
            Reads: self.data["users"] - to retrieve user entry.
            Reads: self.data["users"][username]["favorites"] - to retrieve alias mapping.
            Does not mutate any data.

        Side effects:
            None (read-only operation, no I/O beyond memory access).

        Thread safety:
            Thread-safe for reads. Multiple concurrent calls are safe.
            Parent Data class holds data in memory after initial load.

        Children:
            - self.get_data("users"): Retrieves users dictionary.
            - dict.get(username, {}).get("favorites", {}).get(alias): Nested lookup with defaults.

        Parents:
            - ControlHandler._handle_command(): Retrieves favorite when "/trans fav <alias>" is issued.
            - Connection management code resolving aliases to connection strings.
        """
        users = self.get_data("users")
        return users.get(username, {}).get("favorites", {}).get(alias)
    
    def get_favorites(self, username) -> Dict[str, str]:
        """
        Retrieves all favorites for a user as a dictionary mapping alias to connection string.

        Args:
            username (str): The username whose favorites to retrieve.
                Valid values: Any string. Non-existent usernames return empty dict.

        Returns:
            Dict[str, str]: Dictionary mapping alias names to connection strings.
                - Returns empty dict {} if username does not exist.
                - Returns empty dict {} if user exists but has no favorites.
                - Returns Dict[str, str] with alias->conn_str mappings otherwise.
                Shape: {"alias1": "proto:enc:dialect:host:port", ...}

        Raises:
            None (safe to call with any input, returns empty dict on errors).

        Data:
            Reads: self.data["users"] - to retrieve user entry.
            Reads: self.data["users"][username]["favorites"] - dictionary of all favorites.
            Does not mutate any data.

        Side effects:
            None (read-only operation, no I/O beyond memory access).

        Thread safety:
            Thread-safe for reads. Multiple concurrent calls are safe.
            Parent Data class holds data in memory after initial load.

        Children:
            - self.get_data("users"): Retrieves users dictionary.
            - dict.get(username, {}).get("favorites", {}): Nested lookup with defaults.

        Parents:
            - Admin/management tools displaying all user favorites.
            - UI components listing saved connections.
        """
        users = self.get_data("users")
        return users.get(username, {}).get("favorites", {})

    def _hash_password(self, password, salt):
        """
        Generates a SHA256 hash of the password concatenated with the salt.

        Args:
            password (str): The plaintext password to hash.
                Valid values: Any string (including empty string).
            salt (str): The salt to concatenate with password before hashing.
                Valid values: Any string. Typically 32-char hex string from os.urandom(16).hex().

        Returns:
            str: Hex digest of SHA256 hash (64-character lowercase hex string).
                Format: "abc123..." (64 characters, hexadecimal).

        Raises:
            None (hashlib.sha256 does not raise exceptions for valid string inputs).

        Data:
            Does not read or write any persistent data structures.
            Pure computation using provided arguments.

        Side effects:
            None (pure function, no I/O, no state mutation).

        Thread safety:
            Thread-safe. Pure function with no shared state.

        Children:
            - hashlib.sha256((password + salt).encode()): Creates SHA256 hasher.
            - .hexdigest(): Returns hex string representation of digest.

        Parents:
            - self.create_user(): Hashes password when creating new user account.
            - self.validate_user(): Hashes provided password for comparison with stored hash.
        """
        return hashlib.sha256((password + salt).encode()).hexdigest()
