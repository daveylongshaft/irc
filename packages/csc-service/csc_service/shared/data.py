"""
Persistent data storage module for the CSC shared package.

Provides the Data class which extends Log with methods for storing
and retrieving data using JSON text files as a backend. Supports
thread-safe operations with in-memory caching and automatic file
synchronization.

Module Overview:
    This module defines the Data class, the third level in the CSC framework
    inheritance hierarchy (Root -> Log -> Data -> Version -> Network -> Service).
    It provides a simple key-value store backed by JSON files with automatic
    persistence and in-memory caching for performance.

Classes:
    Data: Extends Log, adds JSON-backed persistent storage

Storage Model:
    - In-memory dictionary (self._storage) holds all data
    - Single JSON file on disk (default: "data.json") for persistence
    - Automatic load on connect(), explicit save on put_data() or store_data()
    - No automatic save on get_data() - purely read from memory

Dependencies:
    - os: For file existence checks
    - json: For serialization/deserialization
    - threading: For thread-safe storage operations
    - .log.Log: Parent class providing logging functionality

Thread Safety:
    - Uses self._storage_lock (threading.Lock) to protect file writes
    - Read operations (get_data) are NOT locked - may see stale data
    - Concurrent writes are serialized via lock
    - Lock held only during disk I/O, not during memory operations

Side Effects:
    - Reads from JSON file on connect()
    - Writes to JSON file on put_data(flush=True) and store_data()
    - Prints connection status to console
    - Logs via inherited log() method

Data Integrity:
    - JSON decode errors caught and logged, empty store initialized
    - File corruption results in data loss (no backup/recovery)
    - No transactional guarantees - partial writes possible on crash

Usage:
    This class is designed to be subclassed:
        class Version(Data):
            def __init__(self):
                super().__init__()
                # Version-specific initialization

    Or used directly for simple key-value persistence:
        data = Data()
        data.put_data("key", {"nested": "value"})
        value = data.get_data("key")

Attributes (Instance):
    name (str): Instance identifier, default "data"
    _storage (dict): In-memory key-value store
    _storage_lock (threading.Lock): Protects file operations
    _connected_source (str or None): Path to connected JSON file
    source_filename (str): Default JSON filename, default "data.json"
    isDataConnected (bool): Connection status flag

Parents:
    - Subclassed by Version class
    - Used by Server and other components needing persistence

Children:
    - Version, Network, Service classes in the hierarchy
"""

import os
import json
import threading
from pathlib import Path
from csc_service.shared.log import Log


def _get_run_dir():
    """Get the runtime state directory without instantiating Platform (avoids circular init)."""
    temp_root = os.environ.get("TEMP") or os.environ.get("TMP") or "/tmp"
    path = Path(temp_root) / "csc" / "run"
    os.makedirs(path, exist_ok=True)
    return path


class Data(Log):
    """
    Extends the log class.

    This class provides methods for persistent data storage and retrieval
    using simple JSON text files as a backend.
    """

    def __init__(self):
        """
        Initializes the Data class.

        - What it does: Sets the instance name, initializes the in-memory data
          storage, and sets the default data source filename.
        - Arguments: None.
        - What calls it: Called by the `__init__` method of its direct subclass, `Version`.
        - What it calls: `super().__init__()`, `print()`.
        """
        super().__init__()
        self.name = "data"
        self._storage = {}
        self._storage_lock = threading.Lock()
        self._connected_source = None
        self.source_filename = "data.json"
        self.isDataConnected = False
        self.connect()
        #print(f"{self.name}->",end=None)

    def connect(self):
        """
        Connects to a data source file.

        - What it does: If the source file exists, it is loaded into the in-memory
          `_storage` dictionary. If not, an empty dictionary is initialized.
          Handles JSON decoding errors by initializing an empty store.
        - Arguments: None.
        - What calls it: Called by `init_data()` and can be called directly by
          subclass instances, such as in `Server.__init__()`.
        - What it calls: `self.log()`, `os.path.exists()`, `open()`, `json.loads()`.
        """
        if (self.isDataConnected == True) :
            return

        from pathlib import Path

        source_filename = self.source_filename

        if os.path.isabs(source_filename):
            path = Path(source_filename)
        else:
            path = _get_run_dir() / source_filename
            
        print( f"Connecting to data source: {path}" )
        self._connected_source = str(path)
        try:
            if os.path.exists( self._connected_source ):
                with open( self._connected_source, 'r' ) as f:
                    content = f.read()
                    self._storage = json.loads( content ) if content else {}
            else:
                self._storage = {}
            print( f"Connection successful. Loaded {len( self._storage )} items from '{path}'." )
            #print( f"Connected to data source: {path}" )
            self.isDataConnected = True
            return True
        except (json.JSONDecodeError, IOError) as e:
            self.log( f"Error or corruption in '{path}'. Initializing empty store. Error: {e}" )
            self._storage = {}
            return False

    def put_data(self, key: str, value, flush=True):
        """
        Stores a key-value pair and saves the entire data store to file.

        - What it does: Updates the in-memory `_storage` dictionary with a new
          key-value pair, then writes the entire dictionary to the connected
          JSON file.
        - Arguments:
            - `key` (str): The key for the data to be stored.
            - `value`: The value to be stored.
        - What calls it: Called by subclass instances, such as `Server.sync_persistent_clients()`.
        - What it calls: `self.log()`, `open()`, `json.dump()`.
        """
        if not self._connected_source:
            self.log( "Error: Not connected to a data source. Use connect() first." )
            return
        self._storage[key] = value

        if flush: self.store_data()
        return True

    def store_data(self):
        """
        Persists the current data to the storage backend.

        - What it does: Writes the entire in-memory `_storage` dictionary to the
          connected JSON file in a thread-safe manner. Logs any I/O errors.
        - Arguments: None.
        - What calls it: Called by `put_data()` when flush=True and can be called
          directly by subclass instances.
        - What it calls: `open()`, `json.dump()`, `self.log()`, `print()`.
        - Returns: True if successful, otherwise returns after logging error.
        """
        if not self._connected_source:
            self.log( "Error: Not connected to a data source. Use connect() first." )
            return
        source_filename = self._connected_source
        try:
            with self._storage_lock:
                with open( self._connected_source, 'w' ) as f:
                    json.dump( self._storage, f, indent=4 )
        except IOError as e:
            self.log( f"Error: Could not save data to {self._connected_source}. Error: {e}" )

        print( f"Store data successful. saved {len( self._storage )} items to '{source_filename}'." )
        return True

    def get_data(self, key: str):
        """
        Retrieves a value from the in-memory data store.

        - What it does: Gets the value associated with the given key from the
          `_storage` dictionary.
        - Arguments:
            - `key` (str): The key of the data to retrieve.
        - What calls it: Called by subclass instances, such as `Server.__init__()`.
        - What it calls: `dict.get()`.
        """
        return self._storage.get(key, None)

    def init_data(self, source_filename = "default"):
        """
        Initializes or re-initializes the data object for a subclass instance.

        - What it does: Resets the in-memory storage, sets the data source
          filename based on the instance's `name` attribute, and connects to
          the new source file.
        - Arguments: None.
        - What calls it: Called by subclass instances, such as `Server.__init__()`.
        - What it calls: `self.connect()`.
        """
        if source_filename == "default":
            self.source_filename = f"{self.name}_data.json"
        else:
            self.source_filename = source_filename
        self._storage = {}
        self.isDataConnected = False
        self._connected_source = None
        self.connect()

    def run(self):
        """
        Main execution method for standalone testing.

        - What it does: Connects to the data source when the module is run directly.
        - Arguments: None.
        - What calls it: Called by `if __name__ == '__main__'` block.
        - What it calls: `self.connect()`.
        - Returns: None.
        """
        self.connect()

if __name__ == '__main__':
    data = Data()
    data.run()

