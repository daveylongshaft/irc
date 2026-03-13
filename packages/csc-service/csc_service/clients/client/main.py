import sys, os, argparse
from pathlib import Path

_client_dir = Path(__file__).resolve().parent
_csc_service_root = _client_dir.parent.parent  # clients/client -> csc_service
_shared_dir = _csc_service_root / 'shared'
_server_dir = _csc_service_root / 'server'

sys.path.insert(0, str(_client_dir))
sys.path.insert(0, str(_shared_dir))
sys.path.insert(0, str(_server_dir))

from csc_service.shared.platform import Platform
_project_root = Platform.PROJECT_ROOT
os.chdir(str(_project_root))
if str(_project_root) not in sys.path:
    sys.path.append(str(_project_root))

from csc_service.clients.client.client import Client


def main():
    parser = argparse.ArgumentParser(description="CSC IRC Client")
    parser.add_argument("config", nargs="?", help="Path to config file")
    parser.add_argument("--infile", help="Read commands from file or FIFO instead of stdin")
    parser.add_argument("--outfile", help="Append server output to this file")
    parser.add_argument("--detach", action="store_true", help="Run headlessly (no interactive prompt)")
    parser.add_argument(
        "--fifo",
        action="store_true",
        help="Daemon mode: create and read from a FIFO at <run_dir>/client.in (Linux only)",
    )
    args = parser.parse_args()

    input_file = args.infile
    output_file = args.outfile
    interactive = not args.detach

    if args.fifo:
        fifo_dir = Platform.PROJECT_ROOT / "tmp" / "csc" / "run"
        fifo_dir.mkdir(parents=True, exist_ok=True)

        is_windows = os.name == 'nt'

        if is_windows:
            # Windows: use a regular file (since we can't reliably create named pipes cross-platform)
            # Agents/scripts can write to this file, client will continuously read it
            fifo_path = fifo_dir / "client.in"
            print(f"[csc-client] Daemon mode: reading from file {fifo_path}")
            print(f"[csc-client] Send commands (cmd.exe): echo COMMAND >> {fifo_path}")
            print(f"[csc-client] Or PowerShell: Add-Content {fifo_path} -Value 'COMMAND'")
            print(f"[csc-client] Note: clear the file periodically (del {fifo_path}) to reset")
            fifo_path = str(fifo_path)
        else:
            # Linux/Mac: use POSIX FIFO (true named pipe)
            fifo_path = fifo_dir / "client.in"
            if not fifo_path.exists():
                os.mkfifo(str(fifo_path))
            print(f"[csc-client] Daemon mode: reading from FIFO {fifo_path}")
            print(f"[csc-client] Send commands: echo COMMAND > {fifo_path}")
            fifo_path = str(fifo_path)

        input_file = fifo_path
        if not output_file:
            output_file = str(fifo_dir / "client.out")
        interactive = False

    client = Client(config_path=args.config, input_file=input_file, output_file=output_file)
    client.run(interactive=interactive)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
