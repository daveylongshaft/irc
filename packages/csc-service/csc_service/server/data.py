import os
import json
import threading
from csc_log import Log

class Data(Log):
    """
    Extends the log class.

    This class provides methods for persistent data storage and retrieval
    using simple JSON text files as a backend.
    """

    @property
    def storage(self):
        """
        Returns the in-memory data storage dictionary.
        """
        return self._storage

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
        source_filename = self.source_filename
        print( f"Connecting to data source: {source_filename}" )
        self._connected_source = source_filename
        try:
            if os.path.exists( self._connected_source ):
                with open( self._connected_source, 'r' ) as f:
                    content = f.read()
                    self._storage = json.loads( content ) if content else {}
            else:
                self._storage = {}
            print( f"Connection successful. Loaded {len( self._storage )} items from '{source_filename}'." )
            #print( f"Connected to data source: {source_filename}" )
            self.isDataConnected = True
            return True
        except (json.JSONDecodeError, IOError) as e:
            self.log( f"Error or corruption in '{source_filename}'. Initializing empty store. Error: {e}" )
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
        self.storage[key] = value

        if flush: self.store_data()
        return True

    def store_data(self):

        """
        Persists the current data to the storage backend.
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
        Main execution method.
        """
        self.connect()

if __name__ == '__main__':
    data = Data()
    data.run()
