import sys
from .client import GeminiClient

def main():
    """
    Main entry point for the csc-gemini agent.
    """
    config_path = sys.argv[1] if len(sys.argv) > 1 else None
    client = GeminiClient(config_path=config_path)
    client.run()

if __name__ == "__main__":
    main()
