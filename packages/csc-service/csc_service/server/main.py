import sys, os
from pathlib import Path

_server_dir = Path(__file__).resolve().parent
_csc_service_root = _server_dir.parent  # server -> csc_service
_shared_dir = _csc_service_root / 'shared'

# Add to path early so Platform can be imported
sys.path.insert(0, str(_shared_dir))
sys.path.insert(0, str(_server_dir))

from csc_service.shared.platform import Platform
_project_root = Platform.PROJECT_ROOT

os.chdir(str(_project_root))

if str(_project_root) not in sys.path:
    sys.path.append(str(_project_root))

from server import Server

def main():
    # --daemon flag: force headless mode (no TTY client, pure network server)
    if '--daemon' in sys.argv:
        os.environ['CSC_HEADLESS'] = 'true'
    Server().run()

if __name__ == "__main__":
    main()
