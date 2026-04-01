import requests
from csc_services import Service


class curl( Service ):
    """
    A service to perform basic cURL-like web requests.
    Supports:
    - POST/PUT with -d (data)
    - Setting headers with -H
    - Targeting a URL
    """

    def __init__(self, server_instance):
        """Initializes the Curl service."""
        super().__init__( server_instance )
        self.log( "Curl service initialized." )

    def run(self, *args):
        """
        Parses curl-like arguments to make an HTTP request.
        Example: AI <token> Curl run -H "Title: test" -d "body" https://ntfy.sh/topic
        """
        url = None
        headers = {}
        data = None
        method = 'GET'  # Default method

        try:
            i = 0
            while i < len( args ):
                arg = args[i]
                if arg == '-H':  # Header
                    i += 1
                    header_str = args[i]
                    key, val = header_str.split( ':', 1 )
                    headers[key.strip()] = val.strip()
                elif arg == '-d':  # Data
                    i += 1
                    data = args[i]
                    method = 'POST'  # Sending data implies POST
                elif not arg.startswith( '-' ):
                    url = arg

                i += 1

            if not url:
                return "Error: No URL specified."

            self.log( f"Curl service running: {method} {url} | Headers: {headers} | Data: {data}" )

            if method == 'POST':
                response = requests.post( url, data=data.encode( 'utf-8' ), headers=headers, timeout=10 )
            else:  # Default to GET
                response = requests.get( url, headers=headers, timeout=10 )

            response.raise_for_status()  # Raise an exception for bad status codes

            # --- MODIFICATION ---
            # Return the full response.text, not just the first 100 characters.
            return f"Success ({response.status_code}). Response: {response.text}"
            # --- END MODIFICATION ---

        except Exception as e:
            self.log( f"Curl service error: {e}" )
            return f"Error: {e}"

    def default(self, *args):
        """Default help message."""
        return "Curl service ready. Use 'run' method with curl-like flags (-H, -d, <url>)."