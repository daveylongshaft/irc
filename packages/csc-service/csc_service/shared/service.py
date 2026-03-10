"""
Base Service class for CSC service modules.

This module provides the Service base class that all service modules in
csc_shared/services/ inherit from. It provides methods for data persistence,
logging, and server access.

Classes:
    Service: Base class for all CSC services
"""

try:
    from .data import Data
except (ImportError, ValueError):
    from data import Data


class Service(Data):
    """
    Base class for all CSC service modules.

    Inherits from Data to provide:
    - init_data() - Initialize data storage for this service
    - get_data(key) - Retrieve persisted data
    - put_data(key, value) - Store persisted data
    - log(message) - Log messages with timestamp

    Service modules should:
    - Inherit from this class
    - Define __init__(self, server_instance)
    - Call self.init_data() to set up persistence
    - Call self.log() for logging
    """

    def __init__(self, server_instance):
        """
        Initialize a service.

        Args:
            server_instance: Reference to the CSC server for API access
        """
        super().__init__()
        self.server = server_instance
        self.name = self.__class__.__name__.lower()

    def default(self, *args):
        """
        Default handler called when a method is not found.

        Subclasses should override this to provide default behavior.

        Args:
            *args: Arguments passed to the missing method

        Returns:
            str: Help message or error message
        """
        return f"No default handler in {self.name} service"
