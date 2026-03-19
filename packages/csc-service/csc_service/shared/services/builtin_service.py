import base64
import os
import shutil
import datetime
import ftplib
from typing import List, Union
from csc_service.server.service import Service
from pathlib import Path
from csc_service.shared.secret import get_known_core_files # Import get_known_core_files

try:
    import requests
except ImportError:
    requests = None


class builtin( Service ):

    # --- Basic Echo and Status ---
    def echo(self, *args: str) -> str:
        """
        Echoes back the given arguments.
        """
        message = " ".join( args )
        self.log( f"Entering echo with args: {args}" )
        self.log( f"Built-in echo: '{message}'" )
        return f"Echo: {message}"

    def status(self) -> str:
        """
        Returns the status of the system.
        """
        self.log( "Entering status function." )
        self.log( "Built-in status cmd executed." )
        return "System running. Built-in services are operational."

    def current_time(self) -> str:
        """
        Returns the current server time.
        """
        self.log( "Entering current_time function." )
        now = datetime.datetime.now().strftime( '%Y-%m-%d %H:%M:%S' )
        self.log( f"Built-in current_time: {now}" )
        return f"Current server time: {now}"

    # --- URL Operations ---
    def download_url_content(self, url: str) -> str:
        """
        Downloads the content of a URL.
        """
        self.log( f"Entering download_url_content with url: {url}" )
        if requests is None:
            return "Error: 'requests' module not installed. Run: pip install requests"
        self.log( f"Built-in: Download content from URL: {url}" )
        try:
            response = requests.get( url, timeout=15 )
            response.raise_for_status()
            self.log( f"Successfully fetched content from {url}. Content length: {len( response.text )}" )
            return response.text
        except requests.exceptions.RequestException as e:
            self.log( f"Built-in URL DL err {url}: {e}" )
            return f"Error DL URL {url}: {e}"
        except Exception as e:
            self.log( f"Built-in URL DL unexpected err {url}: {e}" )
            return f"Unexpected err DL URL {url}: {e}"

    def download_url_to_file(self, url: str, local_filepath: str) -> str:
        """
        Downloads the content of a URL to a file.
        """
        self.log( f"Entering download_url_to_file with url: {url}, local_filepath: {local_filepath}" )
        if requests is None:
            return "Error: 'requests' module not installed. Run: pip install requests"
        abs_path = os.path.abspath( local_filepath )
        self.log( f"Built-in: Download URL {url} to UNRESTRICTED file path {abs_path}" )
        # Version the target file before overwriting
        if os.path.exists( abs_path ):
            try:
                self.server.create_new_version( abs_path )
                self.log( f"Versioned {abs_path} before download overwrite." )
            except Exception as e:
                self.log( f"Warning: Could not version {abs_path} before overwrite: {e}" )
        try:
            response = requests.get( url, stream=True, timeout=60 )
            response.raise_for_status()
            os.makedirs( os.path.dirname( abs_path ), exist_ok=True )
            with open( abs_path, 'wb' ) as f:
                for chunk_num, chunk in enumerate( response.iter_content( chunk_size=8192 ) ):
                    f.write( chunk )
                    # self.log( f"Wrote chunk {chunk_num} for {url} to {abs_path}" ) # Too verbose
            self.log( f"Built-in: Downloaded {url} to {abs_path}" )
            return f"Successfully downloaded {url} to {abs_path}"
        except requests.exceptions.RequestException as e:
            self.log( f"Built-in DL {url} to {abs_path} err: {e}" );
            return f"Error DL {url} to {abs_path}: {e}"
        except IOError as e:
            self.log( f"Built-in IO Err save to {abs_path}: {e}" );
            return f"IO Err save to {abs_path}: {e}"
        except Exception as e:
            self.log(
                f"Built-in Unexpected DL err {url} to {abs_path}: {e}" );
            return f"Unexpected err DL {url} to {abs_path}: {e}"

    # --- Local File System Operations (UNRESTRICTED) ---
    CORE_SAFEGUARD_PATHS = ["/", "/bin", "/etc", "/usr", "/var", "/sbin", "/dev", "/proc", "/sys",
                            "C:\\", "C:\\Windows", "C:\\Program Files", "C:\\Program Files (x86)"]

    def _add_core_files_to_safeguards(self):
        """Dynamically adds core project files to the list of safeguarded paths."""
        if self.server and hasattr(self.server, 'project_root_dir'):
            project_root = Path(self.server.project_root_dir)
            core_files_relative = get_known_core_files()
            for rel_path in core_files_relative:
                try:
                    # Resolve absolute path for safeguarding
                    core_path = (project_root / rel_path).resolve()
                    # Add only the file path itself, NOT its parent directory
                    # This protects core files from deletion/modification but allows
                    # directory creation in the project root
                    self.SAFEGUARD_PATHS.append(str(core_path))
                except Exception as e:
                    self.log(f"Warning: Could not add core path {rel_path} to safeguards: {e}")
        else:
            self.log("Warning: Server instance or project_root_dir not available for core file safeguards.")

    def __init__(self, server_instance):
        """
        Initialize the builtin service with server instance and safeguards.

        Args:
            server_instance: Service server instance to delegate logging and
                versioning operations to. Type: Service or subclass. Must have
                log() and create_new_version() methods.

        Returns:
            None

        Raises:
            None explicitly. Parent class __init__ may raise if server_instance
            is invalid.

        Data:
            Initializes self.name = "builtin" (str)
            Initializes self.SAFEGUARD_PATHS as deep copy of CORE_SAFEGUARD_PATHS
            list, extended with core project file paths. Contains absolute paths
            as strings to prevent file system operations on protected locations.

        Side effects:
            - Calls super().__init__(server_instance) which initializes parent
              Service class
            - Calls self._add_core_files_to_safeguards() which reads server's
              project_root_dir and appends core file paths to safeguards
            - Logs initialization message to server logger via self.log()

        Thread safety:
            Not thread-safe. Assumes single initialization per instance.

        Children:
            Calls super().__init__() (parent Service class)
            Calls self._add_core_files_to_safeguards()
            Calls self.log()

        Parents:
            Called by external code instantiating builtin service, typically
            during server initialization.
        """
        super().__init__(server_instance)
        self.name = "builtin"

        # Initialize instance-specific safeguards
        self.SAFEGUARD_PATHS = list(self.CORE_SAFEGUARD_PATHS)
        self._add_core_files_to_safeguards()

        self.log(f"Builtin service initialized with {len(self.SAFEGUARD_PATHS)} safeguarded paths.")

    def list_dir(self, path_argument: str = ".") -> str:
        """
        Lists the contents of a directory.
        """
        self.log( f"Entering list_directory with path_argument: '{path_argument}'" )  # Corrected log message
        target_path = os.path.abspath( path_argument )
        self.log( f"Built-in: Listing UNRESTRICTED directory {target_path}" )
        try:
            if not os.path.exists( target_path ): return f"Error: Path '{target_path}' does not exist."
            if not os.path.isdir( target_path ): return f"Error: Path '{target_path}' is not a directory."
            items = os.listdir( target_path )
            if not items: return f"Directory '{target_path}' is empty."
            output_items = []
            for item in items:
                item_path = os.path.join( target_path, item )
                item_type = "/" if os.path.isdir( item_path ) else ""
                output_items.append( f"{item}{item_type}" )
            output = "\n".join( output_items )
            return output  # No need to strip, join handles it
        except Exception as e:
            # Corrected log message to use target_path
            self.log( f"Built-in: Err list dir {target_path}: {e}" )
            return f"Err list dir {target_path}: {e}"

    def read_file_content(self, filepath: str) -> str:
        """
        Reads the content of a file, making newlines visible.
        """
        self.log( f"Entering read_file_content with filepath: {filepath}" )
        target_filepath = os.path.abspath( filepath )
        self.log( f"Built-in: Reading UNRESTRICTED file: {target_filepath}" )
        try:
            if not os.path.exists( target_filepath ): return f"Error: File '{target_filepath}' does not exist."
            if not os.path.isfile( target_filepath ): return f"Error: Path '{target_filepath}' is not a file."

            with open( target_filepath, "r", encoding="utf-8", errors="replace" ) as f:
                content = f.read()

            self.log( f"Successfully read file {target_filepath}. Content length: {len( content )}" )

            # --- MODIFICATION: Make newlines consistant and wrap for file upload ---
            # Replace different newline types (\r\n, \r) with \n for display
            display_content = content.replace( '\r\n', '\n' ).replace( '\r', '\n' )
            return f"\n<begin file={target_filepath}>\n{content}\n<end file>\n"
            # --- END MODIFICATION
        except Exception as e:
            self.log(
                f"Built-in: Err read file {target_filepath}: {e}" );
            return f"Err read file {target_filepath}: {e}"

    def create_directory_local(self, path_str: str) -> str:
        """ Creates a local directory """
        self.log( f"Entering create_directory_local with path_str: {path_str}" )
        target_path = os.path.abspath( path_str )
        self.log( f"Built-in: Creating UNRESTRICTED directory: {target_path}" )
        
        # Check against normalized paths
        norm_target_path = os.path.normpath( target_path ).lower()
        SAFEGUARD_PATHS_ABS = [os.path.normpath(os.path.abspath( p )).lower() for p in self.SAFEGUARD_PATHS]
        
        # Only block if it's EXACTLY a safeguard path or a critical SUBPATH of one (like C:\Windows\System32)
        # But allow creating new dirs IN the project root if project root is NOT in safeguards.
        if norm_target_path in SAFEGUARD_PATHS_ABS:
            self.log( f"SAFETY PREVENTED: Attempt to create critical system path '{target_path}'." )
            return f"Error: Creating critical system path '{target_path}' is forbidden for safety."
            
        for p in SAFEGUARD_PATHS_ABS:
            # If target is inside a safeguard path (e.g. target is C:\Windows\NewDir)
            if norm_target_path.startswith(p + os.sep) and len(p) > 3: # len > 3 to allow C:\ and /
                self.log( f"SAFETY PREVENTED: Attempt to create path inside critical system directory '{p}'." )
                return f"Error: Creating paths inside '{p}' is forbidden."

        try:
            if os.path.exists( target_path ): return f"Error: Path '{target_path}' already exists."
            os.makedirs( target_path )
            self.log( f"Successfully created directory '{target_path}'." )
            return f"Successfully created directory '{target_path}'."
        except Exception as e:
            self.log( f"Built-in: Err create dir {target_path}: {e}" );
            return f"Err create dir {target_path}: {e}"

    def delete_local(self, path_str: str) -> str:
        """ Deletes a local file or empty directory """
        self.log( f"Entering delete_local with path_str: {path_str}" )
        target_path = os.path.abspath( path_str )
        self.log( f"Built-in: Attempting to delete UNRESTRICTED path: {target_path}." )
        SAFEGUARD_PATHS_ABS = [os.path.abspath( p ) for p in self.SAFEGUARD_PATHS]
        # Check against normalized paths
        norm_target_path = os.path.normpath( target_path ).lower()
        norm_safeguards = [os.path.normpath( p ).lower() for p in SAFEGUARD_PATHS_ABS]

        if norm_target_path in norm_safeguards:
            self.log( f"SAFETY PREVENTED: Attempt to delete critical system path '{target_path}'." )
            return f"Error: Deleting critical system path '{target_path}' is strictly forbidden."
        # Version the file before deleting
        if os.path.isfile( target_path ):
            try:
                self.server.create_new_version( target_path )
                self.log( f"Versioned {target_path} before deletion." )
            except Exception as e:
                self.log( f"Warning: Could not version {target_path} before deletion: {e}" )
        try:
            if not os.path.exists( target_path ): return f"Error: Path '{target_path}' does not exist."
            if os.path.isfile( target_path ):
                os.remove( target_path )
                self.log( f"Successfully deleted file '{target_path}'." )
                return f"Successfully deleted file '{target_path}'."
            elif os.path.isdir( target_path ):
                if not os.listdir( target_path ):
                    os.rmdir( target_path )
                    self.log( f"Successfully deleted empty directory '{target_path}'." )
                    return f"Successfully deleted empty directory '{target_path}'."
                else:
                    return f"Error: Directory '{target_path}' is not empty. Cannot delete."  # Clarified error
            else:
                return f"Error: Path '{target_path}' is not a file or standard directory."
        except Exception as e:
            self.log( f"Built-in: Err delete path {target_path}: {e}" );
            return f"Err delete path {target_path}: {e}"

    def move_local(self, source_path_str: str, destination_path_str: str) -> str:
        """ Moves a local file or directory """
        self.log( f"Entering move_local. Source: {source_path_str}, Destination: {destination_path_str}" )
        source_path = os.path.abspath( source_path_str )
        destination_path = os.path.abspath( destination_path_str )
        self.log( f"Built-in: Moving UNRESTRICTED '{source_path}' to '{destination_path}'" )
        SAFEGUARD_PATHS_ABS = [os.path.abspath( p ) for p in self.SAFEGUARD_PATHS]

        # Normalize paths for safety checks
        norm_source_path = os.path.normpath( source_path ).lower()
        norm_destination_path = os.path.normpath( destination_path ).lower()
        norm_safeguards = [os.path.normpath( p ).lower() for p in SAFEGUARD_PATHS_ABS]
        norm_safeguards_with_sep = [p + os.sep for p in norm_safeguards if len( p ) > 2]

        if norm_source_path in norm_safeguards or any(
                norm_source_path.startswith( p ) for p in norm_safeguards_with_sep ):
            self.log( f"SAFETY PREVENTED: Attempt to move from critical system path '{source_path}'." )
            return f"Error: Moving from critical system path '{source_path}' is forbidden."
        if norm_destination_path in norm_safeguards or any(
                norm_destination_path.startswith( p ) for p in norm_safeguards_with_sep ):
            self.log( f"SAFETY PREVENTED: Attempt to move to critical system path '{destination_path}'." )
            return f"Error: Moving to critical system path '{destination_path}' is forbidden."
        # Version the source file before moving
        if os.path.isfile( source_path ):
            try:
                self.server.create_new_version( source_path )
                self.log( f"Versioned {source_path} before move." )
            except Exception as e:
                self.log( f"Warning: Could not version {source_path} before move: {e}" )
        try:
            if not os.path.exists( source_path ): return f"Error: Source path '{source_path}' does not exist."
            if os.path.exists(
                    destination_path ): return f"Error: Destination path '{destination_path}' already exists."
            if source_path == destination_path: return "Error: Source and destination paths are the same."
            os.makedirs( os.path.dirname( destination_path ), exist_ok=True )
            shutil.move( source_path, destination_path )
            self.log( f"Successfully moved '{source_path}' to '{destination_path}'." )
            return f"Successfully moved '{source_path}' to '{destination_path}'."
        except Exception as e:
            self.log(
                f"Built-in: Err move '{source_path}' to '{destination_path}': {e}" );
            return f"Err move '{source_path}' to '{destination_path}': {e}"

    # --- FTP Operations ---
    # NOTE: These are less commonly used now but kept for potential legacy use.

    def _get_ftp_connection(self, h, p_s, u, pw) -> Union[ftplib.FTP, str]:
        """
        Establishes an FTP connection.
        """
        self.log( f"Attempting FTP connection to {h}:{p_s} as user {u}" )
        try:
            p = int( p_s )
            ftp = ftplib.FTP()
            ftp.connect( h, p, timeout=15 )
            ftp.login( u, pw )
            ftp.set_pasv( True )
            self.log( f"FTP connection successful to {h}:{p}" )
            return ftp
        except ValueError:
            self.log( f"Invalid FTP port '{p_s}'." );
            return f"Err: Invalid FTP port '{p_s}'."
        except ftplib.all_errors as e:
            self.log( f"FTP Conn/Login err {h}:{p_s} as {u}: {e}" );
            return f"FTP Err conn {h}:{p_s} as {u}: {e}"
        except Exception as e:
            self.log( f"FTP Unexpected conn err {h}:{p_s}: {e}" );
            return f"Unexpected FTP conn err: {e}"

    def ftp_connect_list(self, host: str, remote_path: str = ".", port_str: str = "21", user: str = "anonymous",
                         passwd: str = "") -> str:
        """
        Connects to FTP and lists directory contents.
        """
        self.log( f"Entering ftp_connect_list: host={host}, remote_path={remote_path}, port={port_str}, user={user}" )
        ftp_or_err = self._get_ftp_connection( host, port_str, user, passwd )
        if isinstance( ftp_or_err, str ): return ftp_or_err
        ftp = ftp_or_err
        try:
            self.log( f"FTP CWD to '{remote_path}'" )
            ftp.cwd( remote_path )
            lines = []
            self.log( "FTP retrieving LIST" )
            ftp.retrlines( 'LIST', lines.append )
            self.log( f"FTP LIST returned {len( lines )} lines." )
            listing = "\n".join( lines ) if lines else "Directory empty or listing failed."
            return f"FTP List {host}:{port_str}/{remote_path} (user:{user}):\n---\n{listing}\n---"
        except ftplib.all_errors as e:
            self.log(
                f"FTP Err list {remote_path} on {host}: {e}" );
            return f"FTP Err list {remote_path} on {host}: {e}"
        except Exception as e:
            self.log( f"FTP Unexpected list err {remote_path} on {host}: {e}" );
            return f"Unexpected FTP list err: {e}"
        finally:
            # Ensure connection is closed even if CWD or LIST fails
            if isinstance( ftp_or_err, ftplib.FTP ) and getattr( ftp_or_err, 'sock', None ):
                try:
                    ftp_or_err.quit()
                    self.log( f"FTP connection closed for {host}" )
                except Exception:
                    self.log( f"FTP error during quit for {host}", level="warning" )  # Log but don't crash

    def ftp_download_file(self, host: str, remote_filepath: str, local_filepath: str, port_str: str = "21",
                          user: str = "anonymous", passwd: str = "") -> str:
        """
        Downloads a file from an FTP server.
        """
        self.log(
            f"Entering ftp_download_file: host={host}, remote={remote_filepath}, local={local_filepath}, port={port_str}, user={user}" )
        abs_local_path = os.path.abspath( local_filepath )
        self.log( f"FTP DL: ftp://{user}@{host}:{port_str}/{remote_filepath} to effective path {abs_local_path}" )

        ftp_or_err = self._get_ftp_connection( host, port_str, user, passwd )
        if isinstance( ftp_or_err, str ): return ftp_or_err
        ftp = ftp_or_err
        try:
            os.makedirs( os.path.dirname( abs_local_path ), exist_ok=True )
            self.log( f"FTP RETR {remote_filepath} to {abs_local_path}" )
            with open( abs_local_path, 'wb' ) as lf:
                # Use a callback to log progress (optional)
                # bytes_transferred = 0
                # def log_progress(block):
                #      nonlocal bytes_transferred
                #      lf.write(block)
                #      bytes_transferred += len(block)
                #      self.log(f"FTP DL progress: {bytes_transferred} bytes")
                # ftp.retrbinary( f'RETR {remote_filepath}', log_progress )
                ftp.retrbinary( f'RETR {remote_filepath}', lf.write )
            self.log( f"FTP download complete for {remote_filepath}" )
            return f"FTP: Success DL '{remote_filepath}' from {host} to '{abs_local_path}'."
        except ftplib.all_errors as e:
            self.log(
                f"FTP Err DL {remote_filepath} from {host}: {e}" );
            return f"FTP Err DL {remote_filepath} from {host}: {e}"
        except IOError as e:
            self.log(
                f"FTP IO Err save DL to {abs_local_path}: {e}" );
            return f"IO Err save DL to {abs_local_path}: {e}"
        except Exception as e:
            self.log(
                f"FTP Unexpected DL err {remote_filepath} from {host}: {e}" );
            return f"Unexpected FTP DL err: {e}"
        finally:
            if isinstance( ftp_or_err, ftplib.FTP ) and getattr( ftp_or_err, 'sock', None ):
                try:
                    ftp_or_err.quit()
                    self.log( f"FTP connection closed for {host}" )
                except Exception:
                    self.log( f"FTP error during quit for {host}", level="warning" )

    def ftp_upload_file(self, host: str, local_filepath: str, remote_filepath: str, port_str: str = "21",
                        user: str = "anonymous", passwd: str = "") -> str:
        """
        Uploads a file to an FTP server.
        """
        abs_local_path = os.path.abspath( local_filepath )
        self.log(
            f"Entering ftp_upload_file: local={abs_local_path}, remote_ftp://{user}@{host}:{port_str}/{remote_filepath}" )
        if not os.path.exists( abs_local_path ) or not os.path.isfile( abs_local_path ):
            self.log( f"Local file for FTP upload not found: {abs_local_path}" )
            return f"Err: Local file '{abs_local_path}' not found/not file."

        ftp_or_err = self._get_ftp_connection( host, port_str, user, passwd )
        if isinstance( ftp_or_err, str ): return ftp_or_err
        ftp = ftp_or_err
        try:
            remote_dir = os.path.dirname( remote_filepath )
            # Attempt to navigate/create remote directory structure
            if remote_dir and remote_dir not in ['.', '/']:
                dirs = remote_dir.strip( '/' ).split( '/' )
                path_so_far = ''
                for d in dirs:
                    path_so_far = f"{path_so_far}/{d}" if path_so_far else d
                    try:
                        ftp.cwd( path_so_far )
                        self.log( f"FTP: CWD to existing {path_so_far}" )
                    except ftplib.error_perm:
                        self.log( f"FTP: Remote dir '{path_so_far}' not found, attempting MKD." )
                        try:
                            ftp.mkd( path_so_far )
                            self.log( f"FTP: Created remote dir {path_so_far}" )
                            ftp.cwd( path_so_far )  # CWD after creating
                        except ftplib.all_errors as e_mkd:
                            self.log( f"FTP: Could not create/access remote dir {path_so_far}: {e_mkd}" )
                            raise  # Re-raise to fail the upload if dir creation fails

            # Now CWD should be correct, proceed with upload
            self.log( f"FTP STOR {remote_filepath} from {abs_local_path}" )
            with open( abs_local_path, 'rb' ) as lf:
                ftp.storbinary( f'STOR {os.path.basename( remote_filepath )}', lf )  # Use basename for STOR
            self.log( f"FTP upload complete for {remote_filepath}" )
            return f"FTP: Success UL '{abs_local_path}' to '{remote_filepath}' on {host}."
        except ftplib.all_errors as e:
            self.log(
                f"FTP Err UL {abs_local_path} to {host}: {e}" );
            return f"FTP Err UL {abs_local_path} to {host}: {e}"
        except IOError as e:
            self.log(
                f"FTP IO Err read local {abs_local_path} for UL: {e}" );
            return f"IO Err read local {abs_local_path} for UL: {e}"
        except Exception as e:
            self.log( f"FTP Unexpected UL err {abs_local_path} to {host}: {e}" );
            return f"Unexpected FTP UL err: {e}"
        finally:
            if isinstance( ftp_or_err, ftplib.FTP ) and getattr( ftp_or_err, 'sock', None ):
                try:
                    ftp_or_err.quit()
                    self.log( f"FTP connection closed for {host}" )
                except Exception:
                    self.log( f"FTP error during quit for {host}", level="warning" )

