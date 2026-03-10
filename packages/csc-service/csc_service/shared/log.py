import time
from csc_service.shared.root import Root

class Log(Root):
    """
    Extends the root class.

    Provides a standardize  d base for testing (`help` and `test` methods),
    intended to be overridden by all higher-level classes.
    """

    def __init__(self,server = None):
        """
        Initializes the Log class.

        - What it does: Sets the instance name and defines the log file path.
        - Arguments: None.
        - What calls it: Called by the `__init__` method of its direct subclass, `Data`.
        - What it calls: `super().__init__()`.
        """
        super().__init__()
        self.name = "log"
        self.log_file = f"{self.name}.log"
        #print(f"{self.name}->",end=None)

    @classmethod
    def set_platform_log_dir(cls, log_dir):
        """Stub: platform.py calls this to redirect logs to a platform-detected dir.
        Full implementation belongs in the porting WO."""
        pass

    def log(self, message: str):
        """
        Logs a message to the central project log file and prints to console.

        - What it does: Formats a log entry with a timestamp and the calling class's
          name, prints it to the console, and then appends it to the log file.
        - Arguments:
            - `message` (str): The message to be logged.
        - What calls it: Called by various methods throughout the system.
        - What it calls: `time.strftime()`, `open()`.
        """
        timestamp = time.strftime( "%Y-%m-%d %H:%M:%S" )
        class_name = self.__class__.__name__
        log_entry = f"[{timestamp}] [{class_name}] {message}\n"

        # Print to the local console for immediate feedback
        print( log_entry.strip() )

        try:
            # Append the log entry to the project's log file.
            with open( self.log_file, "a" ) as f:
                f.write( log_entry )
        except Exception as e:
            # If logging fails, print a critical error to the console.
            print( f"CRITICAL: Failed to write to log file '{self.log_file}': {e}" )


    def help(self):
        """
        Displays base help information for the class.

        - What it does: Logs that the help command was called and prints basic
          help information to the console. This method is intended to be
          extended by subclasses.
        - Arguments: None.
        - What calls it: Typically called by the command handling system when a
          user issues a `help` command.
        - What it calls: `self.log()`, `print()`.
        """
        self.log( "Displaying log help information." )
        print( f"\n--- Help for {self.__class__.__name__} ---" )
        print( "  help(): Displays this message." )
        print( "  test(): Runs the module's internal self-test." )

    def test(self):
        """
        Runs a base self-test for the class.

        - What it does: Logs that the test command was called. This method is
          intended to be extended by subclasses to provide specific tests.
        - Arguments: None.
        - What calls it: Typically called by the command handling system when a
          user issues a `test` command.
        - What it calls: `self.log()`.
        """
        self.log( f"Running base self-test for {self.__class__.__name__}." )
        return True

if __name__ == '__main__':
    log = Log()
    log.run()

