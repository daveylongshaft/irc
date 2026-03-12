import sys, os
from csc_service.shared.platform import Platform
from csc_service.server.server import Server

def main():
    # --daemon flag: force headless mode (no TTY client, pure network server)
    if '--daemon' in sys.argv:
        os.environ['CSC_HEADLESS'] = 'true'
    Server().run()

if __name__ == "__main__":
    main()
