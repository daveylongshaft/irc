import sys
import os
import argparse
from pathlib import Path

# Ensure CWD is the app directory
_app_dir = Path(__file__).resolve().parent
os.chdir(_app_dir)

# Add parent directory to path for csc_scriptbot imports
_parent = _app_dir.parent.parent
if str(_parent) not in sys.path:
    sys.path.insert(0, str(_parent))

def main():
    from csc_scriptbot.scriptbot import ScriptBot

    parser = argparse.ArgumentParser(description="CSC Script Runner Bot")
    parser.add_argument("--config", help="Path to config file", default="scriptbot_config.json")
    parser.add_argument("--server", help="Server hostname")
    parser.add_argument("--port", type=int, help="Server port")
    parser.add_argument("--nick", help="IRC nickname")
    args = parser.parse_args()

    # Create config if it doesn't exist
    cfg_path = Path(args.config)
    if not cfg_path.exists():
        import json
        default_cfg = {
            "name": args.nick or "ScriptBot",
            "server_host": args.server or os.getenv("CSC_SERVER_HOSTNAME", "127.0.0.1"),
            "server_port": args.port or int(os.getenv("CSC_SERVER_PORT", "9525")),
            "channels": ["#general"],
            "log_file": "scriptbot.log"
        }
        cfg_path.write_text(json.dumps(default_cfg, indent=2))

    bot = ScriptBot(config_path=args.config, host=args.server, port=args.port)
    if args.nick:
        bot.name = args.nick
        
    bot.run(interactive=False)

if __name__ == "__main__":
    main()
