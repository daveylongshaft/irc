from pathlib import Path
from csc_platform import Platform
from csc_services.file_handler_base import BaseFileHandler


class ClientFileHandler(BaseFileHandler):
    """Client-side service module upload handler.

    Subclasses BaseFileHandler with client context (log, paths, versioning).
    Deploys to the same services/ directory as the server so uploaded modules
    are available to both ClientServiceHandler and the local server.
    See BaseFileHandler for the full upload protocol.
    """

    def __init__(self, client):
        self.client = client
        root = Path(client.project_root_dir).resolve()
        super().__init__(
            log_fn=client.log,
            project_root=root,
            services_dir=Platform.get_services_dir(),
            staging_dir=root / "tmp" / "staging_uploads",
            backup_fn=client.create_new_version if hasattr(client, "create_new_version") else None,
        )
