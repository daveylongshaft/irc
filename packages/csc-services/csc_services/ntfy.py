from csc_services import Service


class ntfy(Service):
    """
    A dedicated service to send notifications via ntfy.sh.
    This service uses the 'curl' service as a reliable backend.
    """

    # --- All methods and variables must be indented inside the class ---
    TOPIC = "gemini_commander"
    NTFY_URL = f"https://ntfy.sh/{TOPIC}"

    def __init__(self, server_instance):
        """
        Initializes the instance.
        """
        super().__init__(server_instance)
        self.log(f"Ntfy service initialized for topic: {self.TOPIC}")

    def send(self, *args):
        """
        Sends a notification to the ntfy.sh topic.
        Usage: send <subject> <body>
        """
        if len(args) < 2:
            return "Error: Usage: ntfy send <subject> \"<body>\""

        subject, body = args[0], " ".join(args[1:])

        # It now correctly looks for loaded_modules on self.server
        curl_instance = self.server.loaded_modules.get("Curl")

        if not curl_instance:
            return "FATAL ERROR: The 'Curl' service is a required dependency but is not loaded."

        self.log(f"Sending notification to ntfy.sh topic '{self.TOPIC}' via curl.")

        # Construct the arguments for the curl service
        curl_args = [
            '-H', f"Title: {subject}",
            '-d', body,
            self.NTFY_URL
        ]

        result = curl_instance.run(*curl_args)
        return f"Notification sent. Curl service response: {result}"

    def default(self, *args):
        """
        Checks service status and shows the configured topic.
        Usage: ntfy
        """
        return f"Ntfy service is ready. Messages will be sent to topic '{self.TOPIC}'."