"""pyftpdlib authorizer: authenticates FTP clients from ftpd_users.json.

Users file format (etc/ftpd_users.json):
{
    "users": {
        "admin": {"password": "changeme", "home": "/", "perm": "elradfmwMT"},
        "csc-node": {"password": "nodepass", "home": "/", "perm": "elr"}
    }
}

Permissions (pyftpdlib convention):
    e = change directory (CWD, CDUP)
    l = list files (LIST, NLST, STAT, MLSD, MLST, SIZE)
    r = retrieve file (RETR)
    a = append data to file (APPE)
    d = delete file/dir (DELE, RMD)
    f = rename file/dir (RNFR, RNTO)
    m = create directory (MKD)
    w = store file (STOR, STOU)
    M = change file mode/attrs (SITE CHMOD)
    T = change file mtime (SITE MFMT)
"""

import json
import logging
from pathlib import Path

from pyftpdlib.authorizers import AuthenticationFailed, DummyAuthorizer

log = logging.getLogger(__name__)


class FtpAuthorizer(DummyAuthorizer):
    """Authenticates FTP clients from a JSON users file.

    Extends pyftpdlib DummyAuthorizer to load users from disk
    and support live reloading.
    """

    def __init__(self, users_path, default_home="/"):
        """Initialize the authorizer.

        Args:
            users_path: Path to ftpd_users.json.
            default_home: Default home directory for users without one specified.
        """
        super().__init__()
        self._users_path = Path(users_path)
        self._default_home = default_home
        self.load_users()

    def load_users(self):
        """(Re)load users from the JSON file."""
        self.user_table.clear()
        if not self._users_path.exists():
            log.warning("FtpAuthorizer: users file not found: %s", self._users_path)
            # Add a default anonymous read-only user
            self.add_user("anonymous", "", self._default_home, perm="elr")
            return

        try:
            data = json.loads(self._users_path.read_text(encoding="utf-8"))
            users = data.get("users", {})
            for username, info in users.items():
                password = info.get("password", "")
                home = info.get("home", self._default_home)
                perm = info.get("perm", "elr")
                self.add_user(username, password, home, perm=perm)
            log.info("FtpAuthorizer: loaded %d users from %s",
                     len(users), self._users_path)
        except Exception as e:
            log.error("FtpAuthorizer: failed to load users: %s", e)
            # Ensure at least anonymous access
            self.add_user("anonymous", "", self._default_home, perm="elr")

    def validate_authentication(self, username, password, handler):
        """Override to provide better error messages."""
        if username not in self.user_table:
            raise AuthenticationFailed(f"No such user: {username!r}")
        stored = self.user_table[username]["pwd"]
        if stored and stored != password:
            raise AuthenticationFailed(f"Authentication failed for {username!r}")
