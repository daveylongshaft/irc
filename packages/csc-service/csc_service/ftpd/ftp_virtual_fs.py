"""pyftpdlib AbstractedFS: presents merged namespace from FtpMasterIndex.

The master's FTP server uses this instead of the real filesystem, so
FTP clients see a unified virtual namespace of all slave files.
"""

import logging
import os
import stat
import time

from pyftpdlib.filesystems import AbstractedFS

log = logging.getLogger(__name__)


class FtpVirtualFs(AbstractedFS):
    """Virtual filesystem backed by FtpMasterIndex.

    pyftpdlib calls methods on this class to list directories, stat files,
    and open files. We intercept these to present the merged slave namespace.
    Real file I/O (RETR/STOR) is handled by FtpHandler which delegates to
    slaves -- this class only handles metadata (LIST, STAT, SIZE, MDTM).
    """

    def __init__(self, root, cmd_channel):
        """Initialize the virtual FS.

        Args:
            root: The "root" directory (ignored, we use virtual paths).
            cmd_channel: The FTPHandler instance.
        """
        super().__init__(root, cmd_channel)
        self._index = cmd_channel.server._ftpd_index
        # Override home and root to be virtual "/"
        self._root = "/"
        self._home = "/"
        self._cwd = "/"

    @property
    def root(self):
        return self._root

    @root.setter
    def root(self, value):
        self._root = "/"

    @property
    def cwd(self):
        return self._cwd

    @cwd.setter
    def cwd(self, path):
        self._cwd = self._normalize(path)

    def ftp2fs(self, ftppath):
        """Convert FTP path to internal virtual path."""
        return self._resolve(ftppath)

    def fs2ftp(self, fspath):
        """Convert internal path back to FTP path."""
        return fspath if fspath.startswith("/") else "/" + fspath

    def validpath(self, path):
        """Check if path is valid (always True in virtual FS)."""
        return True

    def isfile(self, path):
        """Check if virtual path is a file."""
        vpath = self._normalize(path)
        slaves = self._index.lookup(vpath)
        return bool(slaves)

    def isdir(self, path):
        """Check if virtual path is a directory."""
        vpath = self._normalize(path)
        if vpath == "/":
            return True
        # It's a directory if any indexed path starts with it
        prefix = vpath + "/"
        for p in self._index.all_paths():
            if p.startswith(prefix):
                return True
        return False

    def islink(self, path):
        return False

    def lexists(self, path):
        return self.isfile(path) or self.isdir(path)

    def getsize(self, path):
        """Get file size from index metadata."""
        vpath = self._normalize(path)
        slaves = self._index.lookup(vpath)
        if slaves:
            best = max(slaves.values(), key=lambda s: s.get("mtime", 0))
            return best.get("size", 0)
        return 0

    def getmtime(self, path):
        """Get file modification time from index metadata."""
        vpath = self._normalize(path)
        slaves = self._index.lookup(vpath)
        if slaves:
            best = max(slaves.values(), key=lambda s: s.get("mtime", 0))
            return best.get("mtime", 0)
        return 0

    def chdir(self, path):
        """Change current working directory."""
        vpath = self._resolve(path)
        if self.isdir(vpath):
            self._cwd = vpath
        else:
            raise OSError(f"Not a directory: {path}")

    def mkdir(self, path):
        """Directories are implicit in virtual FS -- no-op."""
        pass

    def rmdir(self, path):
        """Cannot remove virtual directories directly."""
        raise OSError("Cannot remove virtual directory")

    def remove(self, path):
        """Remove is handled via slave dispatch, not here."""
        raise OSError("Use FTP DELETE command")

    def rename(self, src, dst):
        """Rename not supported in virtual FS."""
        raise OSError("Rename not supported in virtual filesystem")

    def chmod(self, path, mode):
        pass

    def stat(self, path):
        """Return a stat-like object for the virtual path."""
        vpath = self._normalize(path)
        if self.isfile(vpath):
            size = self.getsize(vpath)
            mtime = self.getmtime(vpath)
            return _VirtualStat(size=size, mtime=mtime, is_dir=False)
        elif self.isdir(vpath):
            return _VirtualStat(size=0, mtime=time.time(), is_dir=True)
        raise OSError(f"No such file: {path}")

    def lstat(self, path):
        return self.stat(path)

    def listdir(self, path):
        """List directory contents."""
        vpath = self._resolve(path)
        entries = self._index.list_dir(vpath)
        return [e["name"] for e in entries]

    def listdirinfo(self, path):
        """List directory with full info (for LIST command)."""
        return self.listdir(path)

    def format_list(self, basedir, listing, ignore_err=True):
        """Yield directory listing lines for LIST command (Unix ls -l style)."""
        for name in listing:
            vpath = self._resolve(basedir + "/" + name)
            try:
                st = self.stat(vpath)
                if st.is_dir:
                    mode_str = "drwxr-xr-x"
                    size = 0
                else:
                    mode_str = "-rw-r--r--"
                    size = st.st_size
                mtime = time.strftime("%b %d %H:%M", time.localtime(st.st_mtime))
                line = f"{mode_str}   1 ftp      ftp      {size:>13} {mtime} {name}\r\n"
                yield line.encode("utf-8")
            except OSError:
                if not ignore_err:
                    raise

    def format_mlsx(self, basedir, listing, perms, facts, ignore_err=True):
        """Yield directory listing lines for MLSD/MLST commands."""
        for name in listing:
            vpath = self._resolve(basedir + "/" + name)
            try:
                st = self.stat(vpath)
                if st.is_dir:
                    ftype = "dir"
                else:
                    ftype = "file"
                mtime_str = time.strftime("%Y%m%d%H%M%S", time.gmtime(st.st_mtime))
                line = f"type={ftype};size={st.st_size};modify={mtime_str}; {name}\r\n"
                yield line.encode("utf-8")
            except OSError:
                if not ignore_err:
                    raise

    def open(self, filename, mode):
        """Open is intercepted by FtpHandler -- should not reach here."""
        raise OSError("File I/O handled by slave transfer layer")

    def _resolve(self, path):
        """Resolve a path relative to cwd."""
        if not path:
            return self._cwd
        path = path.replace("\\", "/")
        if path.startswith("/"):
            return self._normalize(path)
        # Relative path
        if self._cwd == "/":
            return self._normalize("/" + path)
        return self._normalize(self._cwd + "/" + path)

    @staticmethod
    def _normalize(path):
        """Normalize a virtual path."""
        path = path.replace("\\", "/")
        if not path.startswith("/"):
            path = "/" + path
        # Resolve .. and .
        parts = []
        for part in path.split("/"):
            if part == "" or part == ".":
                continue
            elif part == "..":
                if parts:
                    parts.pop()
            else:
                parts.append(part)
        result = "/" + "/".join(parts)
        return result


class _VirtualStat:
    """Minimal stat-like object for virtual files."""

    def __init__(self, size=0, mtime=0, is_dir=False):
        self.st_size = size
        self.st_mtime = mtime
        self.is_dir = is_dir
        if is_dir:
            self.st_mode = stat.S_IFDIR | 0o755
        else:
            self.st_mode = stat.S_IFREG | 0o644
        self.st_uid = 0
        self.st_gid = 0
        self.st_nlink = 1
        self.st_dev = 0
        self.st_ino = 0

    def __getitem__(self, idx):
        """Support tuple-style access (os.stat_result compatibility)."""
        return (
            self.st_mode, self.st_ino, self.st_dev, self.st_nlink,
            self.st_uid, self.st_gid, self.st_size, self.st_mtime,
            self.st_mtime, self.st_mtime,
        )[idx]
