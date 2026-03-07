import json
import os
import shutil
from pathlib import Path
from csc_service.shared.data import Data


class Version( Data ):
    """
    Extends the Data class.
    root -> log -> data -> version
    This class provides a file versioning system, creating backups of files
    in a dedicated 'versions' directory and tracking them with metadata.
    """

    def __init__(self):
        """
        Initializes the Version class.

        - What it does: Sets the instance name, determines the project root,
          and creates the main backup directory for file versions.
        - Arguments: None.
        - What calls it: Called by the `__init__` method of its direct subclass, `Network`.
        - What it calls: `super().__init__()`, `Path.parent.resolve()`, `Path.mkdir()`, `print()`.
        """
        # Initialize the parent class (Data)
        super().__init__()
        self.name = "version"
        # Determine the project's root directory to keep paths consistent.
        self.project_root_dir = Path( __file__ ).parent.resolve()
        # Define and create the main backup folder named 'versions'.
        self.version_backup_dir = self.project_root_dir / "versions"
        try:
            self.version_backup_dir.mkdir( exist_ok=True )
        except:
            print("exists")

        #print(f"{self.name}->",end=None)

    def get_version_dir_for_file(self, filepath: str) -> Path:
        """
        Generates a unique version history directory for a given file.

        - What it does: For a file at 'project/services/auth_service.py', its
          versions will be stored in 'project/versions/services/auth_service.py/'.
        - Arguments:
            - `filepath` (str): The path to the file.
        - What calls it: `restore_version()`, `create_new_version()`.
        - What it calls: `self.log()`, `Path.relative_to()`, `Path.mkdir()`, `Path.resolve()`.
        - Returns:
            - `Path`: The resolved, absolute path to the backup directory for the file.
        """
        self.log( f"Generating version directory for: {filepath}" )
        # Calculate the file's path relative to the project root.
        relative_path = Path( filepath ).relative_to( self.project_root_dir )
        # Create the corresponding backup path inside the main 'versions' directory.
        backup_path = self.version_backup_dir / relative_path
        # Ensure the directory and any necessary parent directories exist.
        backup_path.mkdir( parents=True, exist_ok=True )
        self.log( f"Version directory is: {backup_path.resolve()}" )
        return backup_path.resolve()

    def _get_version_info(self, file_backup_dir: Path) -> dict:
        """
        Reads version metadata from the 'versions.json' file for a specific file.

        - What it does: If the metadata file doesn't exist, it creates a default one.
        - Arguments:
            - `file_backup_dir` (Path): The specific version directory for a file.
        - What calls it: `restore_version()`, `create_new_version()`.
        - What it calls: `self.log()`, `Path.exists()`, `open()`, `json.dump()`, `json.load()`.
        - Returns:
            - `dict`: A dictionary containing the versioning metadata.
        """
        self.log( f"Reading version info from directory: {file_backup_dir}" )
        meta_file = file_backup_dir / "versions.json"
        # If no metadata file exists, create a new one with a default structure.
        if not meta_file.exists():
            self.log( f"Metadata file not found. Creating new one at {meta_file}" )
            initial_data = {"latest": 0, "active": 0, "history": {}}
            with open( meta_file, "w" ) as m:
                json.dump( initial_data, m, indent=4 )
            return initial_data
        # If the file exists, read and return its JSON content.
        with open( meta_file, "r" ) as f:
            version_data = json.load( f )
            self.log( f"Loaded version data: {version_data}" )
            return version_data

    def _write_version_info(self, file_backup_dir: Path, version_info: dict):
        """
        Writes updated version info back to the metadata file.

        - What it does: Saves the provided `version_info` dictionary to the
          `versions.json` file in the specified directory.
        - Arguments:
            - `file_backup_dir` (Path): The specific version directory for a file.
            - `version_info` (dict): The metadata dictionary to write to the file.
        - What calls it: `restore_version()`, `create_new_version()`.
        - What it calls: `self.log()`, `Path.mkdir()`, `open()`, `json.dump()`.
        """
        self.log( f"Writing updated version info to directory: {file_backup_dir}" )
        meta_file = file_backup_dir / "versions.json"
        try:
            # Ensure the target directory exists before attempting to write.
            file_backup_dir.mkdir( parents=True, exist_ok=True )
            # Write the dictionary to the JSON file with indentation for readability.
            with open( meta_file, "w" ) as f:
                json.dump( version_info, f, indent=4 )
            self.log( f"Successfully wrote metadata to {meta_file}" )
        except Exception as e:
            self.log( f"CRITICAL: Failed to write version info to {meta_file}: {e}" )

    def restore_version(self, filepath: str, version: str = "latest"):
        """
        Restores a file to a specific version from its backup history.

        - What it does: Copies a backed-up version of a file over the original
          file and updates the version metadata.
        - Arguments:
            - `filepath` (str): The path to the file to be restored.
            - `version` (str, optional): The version number to restore.
              Defaults to "latest".
        - What calls it: Can be called by subclass instances, for example,
          through a command.
        - What it calls: `self.log()`, `self.get_version_dir_for_file()`,
          `self._get_version_info()`, `Path.exists()`, `shutil.copy2()`,
          `self._write_version_info()`.
        """
        self.log( f"Attempting to restore '{filepath}' to version '{version}'." )
        # Get the version history directory for the file.
        file_backup_dir = self.get_version_dir_for_file( filepath )
        version_info = self._get_version_info( file_backup_dir )

        # Determine the specific version number to restore.
        if version == "latest":
            version_to_restore = version_info["latest"]
            self.log( f"Restoring to latest version: {version_to_restore}" )
        else:
            version_to_restore = int( version )
            self.log( f"Restoring to specified version: {version_to_restore}" )

        # Check if the requested version exists in the history.
        if str( version_to_restore ) not in version_info["history"]:
            self.log( f"Error: Version {version_to_restore} not found for {filepath}" )
            return None

        # Check if the backup file for that version still exists.
        backup_filepath = Path( version_info["history"][str( version_to_restore )] )
        if not backup_filepath.exists():
            self.log( f"Error: Backup file not found at {backup_filepath}" )
            return None

        # Perform the restore by copying the backup file over the original file.
        shutil.copy2( backup_filepath, filepath )
        self.log( f"Successfully copied version {version_to_restore} to {filepath}" )

        # Update the metadata to reflect which version is now active.
        version_info["active"] = version_to_restore
        self._write_version_info( file_backup_dir, version_info )

        self.log( f"SUCCESS: Restored '{filepath}' to version {version_to_restore}" )
        return version_to_restore

    def create_new_version(self, filepath: str):
        """
        Creates a new, sequentially numbered version of a file.

        - What it does: Copies the source file to a versioned backup directory,
          updates the version metadata, and logs the operation.
        - Arguments:
            - `filepath` (str): The full path of the file to be versioned.
        - What calls it: Called by `ServerFileHandler.complete_session()` before
          overwriting a file.
        - What it calls: `self.log()`, `Path.exists()`, `self.get_version_dir_for_file()`,
          `self._get_version_info()`, `shutil.copy2()`, `self._write_version_info()`.
        - Returns:
            - `int` or `None`: The new version number if successful, otherwise `None`.
        """
        try:
            self.log( f"Attempting to create a new version for file: {filepath}" )
            source_path = Path( filepath )

            # Pre-flight check: Ensure the source file actually exists before proceeding.
            if not source_path.exists():
                self.log( f"Error: Cannot create version. Source file not found at {filepath}" )
                return None
            self.log( f"Confirmed source file exists at {source_path.resolve()}" )

            # Use the class's helper method to get the correct backup directory.
            file_backup_dir = self.get_version_dir_for_file( filepath )
            self.log( f"Using backup directory: {file_backup_dir}" )

            # Use the class's helper method to load this file's version metadata.
            version_info = self._get_version_info( file_backup_dir )
            self.log( f"Current version info: {version_info}" )

            # Determine the next version number and update the 'latest' counter.
            new_version_number = version_info.get( "latest", 0 ) + 1
            version_info["latest"] = new_version_number
            version_info["active"] = new_version_number  # The newest version is now active.
            self.log( f"New version number will be: {new_version_number}" )

            # Use the filename format expected by restore_version (e.g., file.py.1).
            backup_filename = f"{source_path.name}.{new_version_number}"
            backup_filepath = file_backup_dir / backup_filename
            self.log( f"New version will be saved to: {backup_filepath}" )

            # Use shutil.copy2 to perform the file copy, preserving metadata.
            shutil.copy2( filepath, backup_filepath )

            # --- FIX ---
            # Explicitly verify that the backup file was created before logging success.
            if Path( backup_filepath ).exists():
                self.log( f"SUCCESS: Verified backup file now exists at {backup_filepath}." )
            else:
                self.log(
                    f"CRITICAL FAILURE: File copy operation failed silently. Backup not found at {backup_filepath}." )
                return None

            # Ensure the 'history' key exists before trying to update it.
            if "history" not in version_info:
                version_info["history"] = {}
            # Update the history record for the restore method.
            version_info["history"][str( new_version_number )] = str( backup_filepath )
            self.log( f"Updated history for version {new_version_number}." )

            # Use the class's helper method to write the updated metadata back.
            self._write_version_info( file_backup_dir, version_info )

            # Notify Workflow service if active
            try:
                if hasattr(self, "server") and hasattr(self.server, "loaded_modules"):
                    workflow = self.server.loaded_modules.get("workflow")
                    if workflow:
                        workflow.version_file(filepath)
            except Exception as e:
                self.log(f"Warning: Failed to notify workflow service: {e}")

            self.log( f"SUCCESS: Created version {new_version_number} for {filepath}" )
            return new_version_number

        except Exception as e:
            # Catch-all for any unexpected errors during the process.
            self.log( f"CRITICAL ERROR in create_new_version: {e}" )
            return None


if __name__ == '__main__':
    version = Version()
    version.run()

