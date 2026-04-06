import os
import sys

def main():
    if '--daemon' in sys.argv:
        os.environ['CSC_HEADLESS'] = 'true'
    from csc_server_core.server import Server
    Server().run()

if __name__ == "__main__":
    main()
