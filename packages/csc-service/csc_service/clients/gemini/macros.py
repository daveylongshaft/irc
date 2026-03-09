from csc_service.shared.data import Data
from csc_service.shared.log import Log

class Macros(Log):
    """
    Manages command macros for the client.

    This class handles the loading, saving, adding, removing, and expanding
    of macros. A macro is a sequence of commands that can be executed
    with a single command. Macros are stored persistently using the Data class.
    """

    def __init__(self, data_object):
        """
        Initializes the Macros class.

        Args:
            data_object: An instance of the Data class to be used for storage.
        """
        super().__init__()
        self.name = "macros"
        self.data = data_object
        # Load macros from the data source, defaulting to an empty dict
        self.macros = self.data.get_data("macros") or {}
        self.log(f"Initialized with {len(self.macros)} macros.")

    def add_macro(self, macro_string):
        """
        Adds a new macro or updates an existing one.

        The macro string is expected in the format: "macro_name = command1; command2; ..."
        For example: "setup = /alias setup_done=echo 'Setup complete'; setup_done"

        Args:
            macro_string (str): The string defining the macro.

        Returns:
            str: A message indicating success or failure.
        """
        self.log(f"Attempting to add macro: {macro_string}")
        if "=" not in macro_string:
            return "Invalid macro format. Use: macro_name = command1; command2; ..."

        macro_name, command_sequence_str = [part.strip() for part in macro_string.split("=", 1)]

        if not macro_name:
            return "Invalid macro format. Macro name cannot be empty."

        # Split the command sequence by semicolons
        commands = [cmd.strip() for cmd in command_sequence_str.split(";") if cmd.strip()]

        if not commands:
            return "Invalid macro format. Command sequence cannot be empty."

        self.macros[macro_name] = commands
        self.data.put_data("macros", self.macros)
        self.log(f"Successfully added/updated macro '{macro_name}' with {len(commands)} commands.")
        return f"Macro '{macro_name}' set."

    def remove_macro(self, macro_name):
        """
        Removes an existing macro.

        Args:
            macro_name (str): The name of the macro to remove.

        Returns:
            str: A message indicating success or failure.
        """
        self.log(f"Attempting to remove macro: {macro_name}")
        if macro_name in self.macros:
            del self.macros[macro_name]
            self.data.put_data("macros", self.macros)
            self.log(f"Successfully removed macro '{macro_name}'")
            return f"Macro '{macro_name}' removed."
        else:
            self.log(f"Macro '{macro_name}' not found for removal.")
            return f"Macro '{macro_name}' not found."

    def list_macros(self):
        """
        Returns a formatted string of all defined macros.
        """
        self.log("Listing all macros.")
        if not self.macros:
            return "No macros defined."

        # Sort macros by name for consistent output
        sorted_macros = sorted(self.macros.items())

        output = ["Defined macros:"]
        for name, commands in sorted_macros:
            output.append(f"  {name}:")
            for command in commands:
                output.append(f"    - {command}")
        return "\n".join(output)

    def expand_macro(self, command_name):
        """
        Expands a macro into a sequence of command strings.

        Args:
            command_name (str): The name of the macro to expand.

        Returns:
            list[str] or None: A list of commands if the macro exists, otherwise None.
        """
        # --- FIX: Commented out spammy log messages ---
        # self.log(f"Attempting to expand macro: {command_name}")
        # --- END FIX ---
        if command_name in self.macros:
            commands = self.macros[command_name]
            # --- FIX: Commented out spammy log messages ---
            # self.log(f"Found macro '{command_name}'. Expanding to {len(commands)} commands.")
            # --- END FIX ---
            return commands
        else:
            # Not a macro, return None
            return None
