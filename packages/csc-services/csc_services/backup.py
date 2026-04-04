import os
import tarfile
import time
import io
import difflib
from pathlib import Path
from csc_services import Service


class backup( Service ):
    """
    Backup service using pure Python (tarfile/shutil).
    Works on both Windows and Linux without external dependencies.

    Commands:
      create <path1> [path2...]  - Create a tar.gz backup of files/directories.
      list                       - List available backup archives.
      restore <archive> <dest>   - Restore a backup archive to a destination.
      diff <archive> <path>      - Compare a file in an archive with the current version.
    """

    def __init__(self, server_instance):
        """
        Initializes the instance.
        """
        super().__init__( server_instance )
        self.name = "backup"
        self.init_data()
        self.backup_dir = os.path.join( os.path.dirname( os.path.dirname( os.path.abspath( __file__ ) ) ), "backups" )
        os.makedirs( self.backup_dir, exist_ok=True )
        self.log( f"Backup service initialized. Backup dir: {self.backup_dir}" )

    def create(self, *paths) -> str:
        """Creates a tar.gz backup of the specified files/directories."""
        if not paths:
            return "Error: No paths specified. Usage: create <path1> [path2...]"

        timestamp = time.strftime( "%Y%m%d_%H%M%S" )
        # Use first path basename as label
        label = os.path.basename( os.path.abspath( paths[0] ) ).replace( " ", "_" )
        archive_name = f"backup_{label}_{timestamp}.tar.gz"
        archive_path = os.path.join( self.backup_dir, archive_name )

        try:
            file_count = 0
            with tarfile.open( archive_path, "w:gz" ) as tar:
                for path in paths:
                    abs_path = os.path.abspath( path )
                    if not os.path.exists( abs_path ):
                        return f"Error: Path '{path}' does not exist."

                    arcname = os.path.basename( abs_path )
                    tar.add( abs_path, arcname=arcname )

                    if os.path.isdir( abs_path ):
                        for root, dirs, files in os.walk( abs_path ):
                            file_count += len( files )
                    else:
                        file_count += 1

            size = os.path.getsize( archive_path )
            size_str = f"{size / 1024:.1f}KB" if size > 1024 else f"{size}B"
            self.log( f"Backup created: {archive_path} ({file_count} files, {size_str})" )

            # Track in data
            history = self.get_data( "backup_history" ) or []
            history.append( {
                "archive": archive_name,
                "paths": list( paths ),
                "created": timestamp,
                "files": file_count,
                "size": size,
            } )
            self.put_data( "backup_history", history )

            return f"Backup created: {archive_name} ({file_count} files, {size_str})"

        except Exception as e:
            self.log( f"Backup creation error: {e}" )
            return f"Error creating backup: {e}"

    def list(self) -> str:
        """Lists all available backup archives."""
        if not os.path.exists( self.backup_dir ):
            return "No backups directory found."

        archives = sorted( [f for f in os.listdir( self.backup_dir ) if f.endswith( ".tar.gz" )] )

        if not archives:
            return "No backup archives found."

        response = "--- Backup Archives ---\n"
        for archive in archives:
            full_path = os.path.join( self.backup_dir, archive )
            size = os.path.getsize( full_path )
            size_str = f"{size / 1024:.1f}KB" if size > 1024 else f"{size}B"
            response += f"  {archive} ({size_str})\n"
        response += f"Total: {len( archives )} archives"
        return response

    def restore(self, archive: str, dest: str = ".") -> str:
        """Restores a backup archive to a destination directory."""
        archive_path = os.path.join( self.backup_dir, archive )
        if not os.path.exists( archive_path ):
            return f"Error: Archive '{archive}' not found in {self.backup_dir}."

        dest_path = os.path.abspath( dest )
        os.makedirs( dest_path, exist_ok=True )

        try:
            with tarfile.open( archive_path, "r:gz" ) as tar:
                # Security: check for path traversal
                for member in tar.getmembers():
                    member_path = os.path.join( dest_path, member.name )
                    if not os.path.abspath( member_path ).startswith( os.path.abspath( dest_path ) ):
                        return f"Error: Archive contains unsafe path: {member.name}"

                tar.extractall( path=dest_path )

            self.log( f"Backup restored: {archive} -> {dest_path}" )
            return f"Restored '{archive}' to '{dest_path}'."

        except Exception as e:
            self.log( f"Backup restore error: {e}" )
            return f"Error restoring backup: {e}"

    def diff(self, archive: str, filepath: str) -> str:
        """Compares a file in a backup archive with its current version on disk."""
        archive_path = os.path.join( self.backup_dir, archive )
        if not os.path.exists( archive_path ):
            return f"Error: Archive '{archive}' not found."

        abs_filepath = os.path.abspath( filepath )
        if not os.path.exists( abs_filepath ):
            return f"Error: Current file '{filepath}' does not exist."

        try:
            # Read current file
            with open( abs_filepath, "r", encoding="utf-8", errors="replace" ) as f:
                current_lines = f.readlines()

            # Read archived version
            basename = os.path.basename( abs_filepath )
            archived_content = None

            with tarfile.open( archive_path, "r:gz" ) as tar:
                for member in tar.getmembers():
                    if member.name.endswith( basename ) or member.name == basename:
                        f = tar.extractfile( member )
                        if f:
                            archived_content = f.read().decode( "utf-8", errors="replace" )
                            break

            if archived_content is None:
                return f"Error: File '{basename}' not found in archive '{archive}'."

            archived_lines = archived_content.splitlines( keepends=True )

            diff_result = difflib.unified_diff(
                archived_lines, current_lines,
                fromfile=f"archive:{archive}/{basename}",
                tofile=f"current:{filepath}",
                lineterm=""
            )

            diff_text = "\n".join( diff_result )
            if not diff_text:
                return f"No differences found between archive and current '{filepath}'."

            return f"--- Diff: {archive} vs current ---\n{diff_text}"

        except Exception as e:
            self.log( f"Backup diff error: {e}" )
            return f"Error comparing files: {e}"

    def default(self, *args) -> str:
        """Shows available commands for the Backup service."""
        return (
            "Backup Service Commands:\n"
            f"  (Backups stored in: {self.backup_dir})\n"
            "  create <path1> [path2...]  - Create a tar.gz backup.\n"
            "  list                       - List available backup archives.\n"
            "  restore <archive> <dest>   - Restore a backup to a destination.\n"
            "  diff <archive> <path>      - Compare archived vs current file."
        )
