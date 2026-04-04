import shlex
import shlex
#from data import Data
#from log import Log
#from client import Client
class Aliases():
    """
    Manages command aliases for the client.

    This class is responsible for loading, saving, adding, removing,
    and expanding command aliases. Aliases are stored persistently
    using the Data class.
    """

    def __init__(self, Client):
        """
        Initializes the Aliases class.

        Args:
            data_object: An instance of the Data class to be used for storage.
        """
        self.parent = Client
        self.log = Client.log
        self.put_data = Client.put_data
        self.get_data = Client.get_data
        #super().__init__()
        self.name = "aliases"

        # Load aliases from the data source, defaulting to an empty dict
        self.aliases = self.get_data("aliases") or {}
        self.log(f"Initialized with {len(self.aliases)} aliases.")

    def add_alias(self, alias_string):
        """
        Adds a new alias or updates an existing one.

        The alias string is expected in the format: "alias_name = command_template"
        For example: "ls = ls -l"

        Args:
            alias_string (str): The string defining the alias.

        Returns:
            str: A message indicating success or failure.
        """
        self.log(f"Attempting to add alias: {alias_string}")
        if "=" not in alias_string:
            return "Invalid alias format. Use: alias_name = command template"

        alias_name, command_template = [part.strip() for part in alias_string.split("=", 1)]

        if not alias_name:
            return "Invalid alias format. Alias name cannot be empty."

        self.aliases[alias_name] = command_template
        self.put_data("aliases", self.aliases)
        self.log(f"Successfully added/updated alias '{alias_name}'")
        return f"Alias '{alias_name}' set."

    def remove_alias(self, alias_name):
        """
        Removes an existing alias.

        Args:
            alias_name (str): The name of the alias to remove.

        Returns:
            str: A message indicating success or failure.
        """
        self.log(f"Attempting to remove alias: {alias_name}")
        if alias_name in self.aliases:
            del self.aliases[alias_name]
            self.put_data("aliases", self.aliases)
            self.log(f"Successfully removed alias '{alias_name}'")
            return f"Alias '{alias_name}' removed."
        else:
            self.log(f"Alias '{alias_name}' not found for removal.")
            return f"Alias '{alias_name}' not found."

    def list_aliases(self):
        """
        Returns a formatted string of all defined aliases.
        """
        self.log("Listing all aliases.")
        if not self.aliases:
            return "No aliases defined."

        # Sort aliases by name for consistent output
        sorted_aliases = sorted(self.aliases.items())

        return "Defined aliases:\n" + "\n".join([f"  {name}: {template}" for name, template in sorted_aliases])

    def expand_aliases_in_string(self, command_string):
        """
        Repeatedly finds and expands all occurrences of aliases within a
        command string until no more expansions can be made.

        Args:
            command_string (str): The full command string to process.

        Returns:
            str: The fully expanded command string.
        """
        previous_string = ""
        current_string = command_string
        # Loop until the string no longer changes, which means all aliases are expanded
        while current_string != previous_string:
            previous_string = current_string
            current_string = self._expand_aliases_single_pass(current_string)
        return current_string

    def _expand_aliases_single_pass(self, command_string):
        """
        Performs a single pass of alias expansion on a command string.

        Args:
            command_string (str): The command string to process.

        Returns:
            str: The command string with one layer of aliases expanded.
        """
        try:
            parts = shlex.split(command_string, posix=False)
        except ValueError:
            parts = command_string.split()

        final_parts = []
        i = 0
        while i < len(parts):
            word = parts[i]
            if word in self.aliases:
                template = self.aliases[word]
                # self.log(f"Found alias '{word}' with template '{template}'") # Left for debugging if needed

                num_args, has_rest_arg = self._count_template_args(template)

                args_to_consume = num_args
                if has_rest_arg:
                    args = parts[i+1:]
                    args_to_consume = len(args)
                else:
                    args = parts[i+1 : i+1+num_args]

                expanded_alias = self._expand_single_alias(template, args)
                final_parts.append(expanded_alias)

                i += 1 + args_to_consume
            else:
                final_parts.append(word)
                i += 1

        return " ".join(final_parts)

    def _count_template_args(self, template):
        """
        Counts the number of unique positional arguments ($1, $2, etc.) and
        checks for a rest argument ($N-).
        """
        import re
        positional_placeholders = re.findall(r'\$(\d+)(?!\-)', template)
        rest_placeholder = re.search(r'\$(\d+)-', template)

        num_positional = 0
        if positional_placeholders:
            num_positional = max(int(p) for p in positional_placeholders)

        has_rest = rest_placeholder is not None

        return num_positional, has_rest

    def _expand_single_alias(self, template, args):
        """Expands a single alias template with the provided arguments."""
        # Handle $N- style arguments first
        for i in range(len(args), 0, -1):
            placeholder = f"${i}-"
            if placeholder in template:
                replacement = " ".join(args[i-1:])
                template = template.replace(placeholder, shlex.quote(replacement))

        # Handle $* (all arguments)
        if "$*" in template:
            template = template.replace("$*", " ".join(shlex.quote(arg) for arg in args))

        # Handle individual $N arguments
        for i, arg in enumerate(args):
            template = template.replace(f"${i+1}", shlex.quote(arg))

        return template

