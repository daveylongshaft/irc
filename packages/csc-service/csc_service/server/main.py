import sys, os
from pathlib import Path

# Get paths for the new csc-service structure
_server_dir = Path(__file__).resolve().parent
_csc_service_root = _server_dir.parent  # Up from server to csc_service
_project_root = _csc_service_root.parent.parent.parent.parent  # Up to /c/csc (csc-service→packages→irc→csc)

# Shared is sibling to server in csc_service
_shared_dir = _csc_service_root / 'shared'

# Set CWD to project root for data files
os.chdir(str(_project_root))

# Add to path: shared first (highest priority), then server, then project root
sys.path.insert(0, str(_shared_dir))
sys.path.insert(0, str(_server_dir))
if str(_project_root) not in sys.path:
    sys.path.append(str(_project_root))

from server import Server

if __name__ == "__main__":
    Server().run()
