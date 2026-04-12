import sys
from .client import CodexClient

def main():
    """
    Main entry point for the csc-codex agent.
    """
    config_path = sys.argv[1] if len(sys.argv) > 1 else None
    client = CodexClient(config_path=config_path)
    client.run()

if __name__ == "__main__":
    main()
