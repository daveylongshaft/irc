import sys
from .client import ChatGPTClient

def main():
    """
    Main entry point for the csc-chatgpt agent.
    """
    config_path = sys.argv[1] if len(sys.argv) > 1 else None
    client = ChatGPTClient(config_path=config_path)
    client.run()

if __name__ == "__main__":
    main()
