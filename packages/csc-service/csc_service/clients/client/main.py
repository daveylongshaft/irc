import sys, os
from pathlib import Path

# Get paths for the new csc-service structure
_client_dir = Path(__file__).resolve().parent
_csc_service_root = _client_dir.parent.parent  # Up from clients/client to csc_service
_project_root = _csc_service_root.parent.parent.parent.parent  # Up to /c/csc (csc-service→packages→irc→csc)

# Shared and server are siblings to clients in csc_service
_shared_dir = _csc_service_root / 'shared'
_server_dir = _csc_service_root / 'server'

# Set CWD to project root for config files
os.chdir(str(_project_root))

# Add to path: client first, then shared, then server, then project root
sys.path.insert(0, str(_client_dir))
sys.path.insert(0, str(_shared_dir))
sys.path.insert(0, str(_server_dir))
if str(_project_root) not in sys.path:
    sys.path.append(str(_project_root))

from client import Client

if __name__ == "__main__":
    config = sys.argv[1] if len(sys.argv) > 1 else None
    Client(config).run()
