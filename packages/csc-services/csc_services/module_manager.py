import os
import sys
import ast
import base64
import shutil
import importlib
from pathlib import Path
from csc_services import Service
from csc_platform import Platform


class module_manager( Service ):
    """
    Dynamic module management for the service system.

    Commands:
      list                         - List all loaded and available service modules.
      read <name>                  - Read the source code of a service module.
      create <name> <content_b64>  - Create a new service module from base64 content.
      rehash <module1> [module2...]- Reload specified service modules.
    """

    def __init__(self, server_instance):
        """
        Initializes the instance.
        """
        super().__init__( server_instance )
        self.name = "module_manager"
        self.services_dir = str(Platform.get_services_dir())
        self.staging_dir = Platform.get_staging_dir()
        self.log( f"Module manager initialized. Services dir: {self.services_dir}" )

    def list(self) -> str:
        """Lists all available and currently loaded service modules."""
        # Find all service files
        available = []
        for filename in sorted( os.listdir( self.services_dir ) ):
            if filename.endswith( "_service.py" ) and not filename.startswith( "__" ):
                module_name = filename.replace( "_service.py", "" )
                full_module = f"services.{module_name}_service"
                loaded = full_module in sys.modules
                status = "[loaded]" if loaded else "[available]"
                available.append( f"  {module_name} {status}" )

        if not available:
            return "No service modules found."

        # Also show loaded instances from server
        loaded_instances = []
        if hasattr( self.server, "loaded_modules" ):
            for name in sorted( self.server.loaded_modules.keys() ):
                loaded_instances.append( f"  {name}" )

        response = "--- Available Service Modules ---\n"
        response += "\n".join( available )

        if loaded_instances:
            response += "\n\n--- Active Instances ---\n"
            response += "\n".join( loaded_instances )

        return response

    def read(self, name: str) -> str:
        """Reads the source code of a service module."""
        filename = f"{name.lower()}_service.py"
        filepath = os.path.join( self.services_dir, filename )

        if not os.path.exists( filepath ):
            return f"Error: Module '{name}' not found at {filepath}."

        try:
            with open( filepath, "r", encoding="utf-8" ) as f:
                content = f.read()
            return f"--- {filename} ---\n{content}"
        except Exception as e:
            return f"Error reading module '{name}': {e}"

    def create(self, name: str, content_b64: str) -> str:
        """Creates a new service module from base64-encoded content."""
        filename = f"{name.lower()}_service.py"
        filepath = os.path.join( self.services_dir, filename )

        if os.path.exists( filepath ):
            # Version existing file before overwriting
            try:
                self.server.create_new_version( filepath )
            except Exception as e:
                self.log( f"Warning: Could not version existing module: {e}" )

        try:
            content = base64.b64decode( content_b64 ).decode( "utf-8" )
        except Exception as e:
            return f"Error: Could not decode base64 content: {e}"

        try:
            with open( filepath, "w", encoding="utf-8" ) as f:
                f.write( content )
            self.log( f"Module '{name}' created at {filepath}" )
            return f"Module '{name}' created successfully at {filepath}."
        except Exception as e:
            return f"Error creating module '{name}': {e}"

    def rehash(self, *names) -> str:
        """Reloads specified service modules."""
        if not names:
            return "Error: No module names specified. Usage: rehash <module1> [module2...]"

        results = []
        for name in names:
            module_path = f"services.{name.lower()}_service"
            try:
                if module_path in sys.modules:
                    importlib.reload( sys.modules[module_path] )
                    # Remove cached instance so it gets re-created on next use
                    if hasattr( self.server, "loaded_modules" ) and name.lower() in self.server.loaded_modules:
                        del self.server.loaded_modules[name.lower()]
                    results.append( f"  {name}: reloaded" )
                else:
                    importlib.import_module( module_path )
                    results.append( f"  {name}: loaded (new)" )
            except Exception as e:
                results.append( f"  {name}: ERROR - {e}" )

        return "--- Rehash Results ---\n" + "\n".join( results )

    def staging(self) -> str:
        """Lists all files in staging_uploads/ waiting for approval."""
        staging_dir = self.staging_dir
        if not staging_dir.exists():
            return "No staging directory found."

        files = []
        for f in sorted(staging_dir.iterdir()):
            if f.is_file() and f.name.endswith("_service.py"):
                files.append(f"  {f.name}")

        if not files:
            return "No service modules in staging."

        return "--- Staged Service Modules ---\n" + "\n".join(files)

    def _validate_service_file(self, filepath: Path, expected_class: str) -> tuple:
        """
        Validates a service file contains exactly one class with the expected name.
        Returns (is_valid, error_message).
        """
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            return False, f"Error reading file: {e}"

        try:
            tree = ast.parse(content)
        except SyntaxError as e:
            return False, f"Python syntax error: {e}"

        # Find all class definitions
        classes = [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]

        if len(classes) == 0:
            return False, "File contains 0 classes. Expected exactly 1."
        if len(classes) > 1:
            return False, f"File contains {len(classes)} classes ({', '.join(classes)}). Expected exactly 1."

        actual_class = classes[0]
        if actual_class.lower() != expected_class.lower():
            return False, f"Class name '{actual_class}' does not match expected '{expected_class}'."

        return True, None

    def approve(self, name: str) -> str:
        """
        Validates and moves a service module from staging_uploads/ to services/.

        Validation checks:
        1. File exists in staging_uploads/
        2. File contains exactly one class definition
        3. Class name matches the service name (case-insensitive)
        """
        staging_dir = self.staging_dir
        filename = f"{name.lower()}_service.py"
        staged_path = staging_dir / filename
        target_path = Path(self.services_dir) / filename
        # Class names use lowercase with underscores (e.g., "builtin", "module_manager")
        expected_class = name.lower()

        if not staged_path.exists():
            return f"Error: '{filename}' not found in staging_uploads/. Use 'staging' to list available files."

        # Validate the file
        is_valid, error = self._validate_service_file(staged_path, expected_class)
        if not is_valid:
            return f"Validation failed for '{name}': {error}"

        # Version existing file if it exists
        if target_path.exists():
            try:
                self.server.create_new_version(str(target_path))
                self.log(f"Versioned existing {filename} before replacement.")
            except Exception as e:
                self.log(f"Warning: Could not version existing module: {e}")

        # Move file to services/
        try:
            shutil.move(str(staged_path), str(target_path))
            self.log(f"Approved and moved {filename} to services/")

            # Clear cached instance so it gets fresh load
            if hasattr(self.server, "loaded_modules") and name.lower() in self.server.loaded_modules:
                del self.server.loaded_modules[name.lower()]

            return f"Service '{name}' approved and activated. Class '{expected_class}' is now available."
        except Exception as e:
            return f"Error moving file to services/: {e}"

    def reject(self, name: str) -> str:
        """
        Deletes a service module from staging_uploads/ (with version backup).
        """
        staging_dir = self.staging_dir
        filename = f"{name.lower()}_service.py"
        staged_path = staging_dir / filename

        if not staged_path.exists():
            return f"Error: '{filename}' not found in staging_uploads/."

        # Version before deleting
        try:
            self.server.create_new_version(str(staged_path))
        except Exception as e:
            self.log(f"Warning: Could not version before rejection: {e}")

        try:
            staged_path.unlink()
            return f"Rejected and deleted '{filename}' from staging."
        except Exception as e:
            return f"Error deleting file: {e}"

    def default(self, *args) -> str:
        """Shows available commands for the Module Manager service."""
        return (
            "Module Manager Service Commands:\n"
            "  list                           - List all active service modules.\n"
            "  staging                        - List files awaiting approval.\n"
            "  approve <name>                 - Validate and activate a staged module.\n"
            "  reject <name>                  - Delete a staged module.\n"
            "  read <name>                    - Read source of a module.\n"
            "  create <name> <content_b64>    - Create module from base64.\n"
            "  rehash <module1> [module2...]  - Reload modules."
        )
