from csc_platform import Platform
from csc_services.file_handler_base import BaseFileHandler
from csc_server_core.irc import SERVER_NAME  # noqa: F401 (kept for callers that import from here)


class FileHandler(BaseFileHandler):
    """Server-side service module upload handler.

    Subclasses BaseFileHandler with server context (log, paths, versioning).
    See BaseFileHandler for the full upload protocol.
    """

    def __init__(self, server):
        self.server = server
        root = Platform.PROJECT_ROOT
        super().__init__(
            log_fn=server.log,
            project_root=root,
            services_dir=Platform.get_services_dir(),
            staging_dir=root / "tmp" / "staging_uploads",
            backup_fn=server.create_new_version if hasattr(server, "create_new_version") else None,
        )
