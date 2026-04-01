from csc_services import Service


class patch_test_dummy( Service ):
    """A dummy service used exclusively as a patch test target.

    This file exists so tests can safely apply patches without touching
    real services.  Do not use this service for anything else.
    """

    def __init__(self, server_instance):
        super().__init__( server_instance )
        self.name = "patch_test_dummy"

    def hello(self):
        """Return a greeting."""
        return "Hello from dummy service"

    def add(self, a, b):
        """Add two numbers."""
        result = int( a ) + int( b )
        return str( result )

    def status(self):
        """Return status string."""
        return "dummy OK"

    def multiply(self, x, y):
        """Multiply two numbers."""
        result = int( x ) * int( y )
        return str( result )

    def default(self, *args):
        """Fallback handler."""
        return f"patch_test_dummy default: {args}"
