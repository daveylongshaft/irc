"""Agent executor: bridges queue_worker to RunAgentExecutor.

Provides a unified interface for queue_worker to spawn agents via
RunAgentExecutor (which handles orders.md, environment setup, etc.).
"""

import sys
from pathlib import Path
from csc_services.services.run_agent_executor import RunAgentExecutor


class AgentExecutor:
    """Wrapper around RunAgentExecutor for queue_worker compatibility."""

    def __init__(self, csc_root: Path):
        """Initialize executor with CSC project root."""
        self.csc_root = Path(csc_root)

    def execute(self, agent_name: str, workorder_path: Path, log_file_path: Path) -> int:
        """Execute an agent for a workorder.

        Args:
            agent_name: Name of agent (haiku, opus, gemini-2.5-pro, etc.)
            workorder_path: Path to WIP workorder file
            log_file_path: Path to write agent stdout/stderr log

        Returns:
            Exit code (0 = success, 1 = failure)
        """
        try:
            # Get agent's queue/in/orders.md path
            from csc_platform import Platform
            queue_in_dir = Platform.get_agent_queue_dir(agent_name, "in")
            orders_path = queue_in_dir / "orders.md"

            if not orders_path.exists():
                print(f"[AgentExecutor] ERROR: orders.md not found at {orders_path}", file=sys.stderr)
                return 1

            # Create and run agent executor
            executor = RunAgentExecutor(
                agent_name=agent_name,
                queue_entry_path=orders_path,
                project_root=self.csc_root
            )

            # Execute and capture return code
            # RunAgentExecutor logs to WIP file automatically
            return_code = executor.execute()

            return return_code

        except Exception as e:
            print(f"[AgentExecutor] ERROR: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc(file=sys.stderr)
            return 1
