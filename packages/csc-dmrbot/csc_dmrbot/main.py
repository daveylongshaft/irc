import sys
from .client import DmrClient

def main():
    """
    Main entry point for the csc-dmrbot agent.
    """
    config_path = sys.argv[1] if len(sys.argv) > 1 else None
    client = DmrClient(config_path=config_path)
    client.run()

if __name__ == "__main__":
    main()
