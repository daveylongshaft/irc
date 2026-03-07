import os
from pathlib import Path
from csc_service.server.service import Service


class version( Service ):
    """
    Chatline-callable wrapper for the server's built-in file versioning system.

    Commands:
      create <filepath>           - Create a new version of a file.
      restore <filepath> [ver]    - Restore a file to a version (default: latest).
      history <filepath>          - Show version history for a file.
      list                        - Show all versioned files.
    """

    def create(self, filepath: str) -> str:
        """Creates a new version backup of the specified file."""
        self.log( f"Version service: create version for {filepath}" )
        abs_path = os.path.abspath( filepath )

        if not os.path.exists( abs_path ):
            return f"Error: File '{filepath}' does not exist."

        version_num = self.server.create_new_version( abs_path )
        if version_num is None:
            return f"Error: Failed to create version for '{filepath}'."

        return f"Created version {version_num} for '{filepath}'."

    def restore(self, filepath: str, version: str = "latest") -> str:
        """Restores a file to a specific version (default: latest)."""
        self.log( f"Version service: restore {filepath} to version {version}" )
        abs_path = os.path.abspath( filepath )

        if not os.path.exists( abs_path ) and version == "latest":
            return f"Error: File '{filepath}' does not exist."

        result = self.server.restore_version( abs_path, version )
        if result is None:
            return f"Error: Failed to restore '{filepath}' to version '{version}'."

        return f"Restored '{filepath}' to version {result}."

    def history(self, filepath: str) -> str:
        """Shows version history for a file."""
        self.log( f"Version service: history for {filepath}" )
        abs_path = os.path.abspath( filepath )

        try:
            file_backup_dir = self.server.get_version_dir_for_file( abs_path )
            version_info = self.server._get_version_info( file_backup_dir )
        except Exception as e:
            return f"Error: Could not read version info for '{filepath}': {e}"

        history = version_info.get( "history", {} )
        if not history:
            return f"No version history found for '{filepath}'."

        latest = version_info.get( "latest", 0 )
        active = version_info.get( "active", 0 )

        response = f"--- Version History for {filepath} ---\n"
        response += f"  Latest: v{latest} | Active: v{active}\n"
        for ver_num in sorted( history.keys(), key=int ):
            marker = " <-- active" if int( ver_num ) == active else ""
            response += f"  v{ver_num}: {os.path.basename( history[ver_num] )}{marker}\n"

        return response.strip()

    def list(self) -> str:
        """Lists all files that have version backups."""
        self.log( "Version service: listing all versioned files" )
        version_dir = self.server.version_backup_dir

        if not version_dir.exists():
            return "No versioned files found."

        versioned_files = []
        for root, dirs, files in os.walk( version_dir ):
            if "versions.json" in files:
                # The directory name relative to version_backup_dir is the file path
                rel_path = Path( root ).relative_to( version_dir )
                versioned_files.append( str( rel_path ) )

        if not versioned_files:
            return "No versioned files found."

        response = "--- Versioned Files ---\n"
        for vf in sorted( versioned_files ):
            response += f"  {vf}\n"
        response += f"Total: {len( versioned_files )} files"
        return response

    def default(self, *args) -> str:
        """Shows available commands for the Version service."""
        return (
            "Version Service Commands:\n"
            "  create <filepath>          - Create a new version of a file.\n"
            "  restore <filepath> [ver]   - Restore a file (default: latest).\n"
            "  history <filepath>         - Show version history for a file.\n"
            "  list                       - Show all versioned files."
        )
