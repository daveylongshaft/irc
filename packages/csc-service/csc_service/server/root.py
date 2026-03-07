from os import listdir
from os.path import dirname
from sys import path
from pathlib import Path
SCRIPT_DIR = dirname(Path(__file__).absolute())
not_at_root = True
while not_at_root:
    if "root.py" in listdir(SCRIPT_DIR):
        not_at_root = False
        PROJECT_ROOT = SCRIPT_DIR
        if SCRIPT_DIR not in path:
            path.append( SCRIPT_DIR )
            #print( f"{SCRIPT_DIR} added to system path" )
    else:
        DIR = Path( SCRIPT_DIR ).parent
        SCRIPT_DIR = DIR
#print(f"system path: {path}")
class Root:
    """
    The first and lowest class in the project's inheritance hierarchy.
    """

    def __init__(self):
        """
        Initializes the Root class.

        - What it does: Sets the ssystem-wide command keyword and the instance name.
        - Arguments: None.
        - What calls it: Called by the `__init__` method of its direct subclass, `Log`.
        - What it calls: `print()`.
        """
        self.command_keyword = "AI"

        self.name = "root"

        print(f"system command keyword is: {self.command_keyword}")

        #self.log(f"{self.name}->")

    def get_command_keyword(self):
        """
        Returns the system command keyword.

        - What it does: A simple getter method to retrieve the command keyword.
        - Arguments: None.
        - What calls it: Can be called by any subclass instance.
        - What it calls: None.
        """
        return self.command_keyword

    def run(self):
        """
        A placeholder method for subclasses to override.

        - What it does: This method is intended to be the main entry point for
          subclasses, such as starting a server's network loop. In the Root
          class, it does nothing.
        - Arguments: None.
        - What calls it: The `if __name__ == '__main__':` block.
        - What it calls: None.
        """
        pass

if __name__ == '__main__':
    root = Root()
    root.run()
