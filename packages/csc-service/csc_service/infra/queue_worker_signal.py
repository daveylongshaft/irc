"""
Queue-Worker Signal Interface.

Provides methods for queue-worker to signal back to PM:
- Workorder started
- Workorder failed (with error details)
- Workorder succeeded
- Workorder in progress (heartbeat)

This is the communication channel between queue-worker and PM.
"""

from csc_service.shared.data import Data


class QueueWorkerSignal(Data):
    """
    Interface for queue-worker to report workorder status to PM.

    Queue-worker calls these methods after each cycle.
    PM periodically checks them to make decisions (retry, switch agent, escalate).
    """

    def __init__(self):
        super().__init__()
        self.name = "queue_worker_signal"
        self.init_data("queue_worker_signals.json")

    # -----------------------------------------------------------------------
    # Signals from queue-worker to PM
    # -----------------------------------------------------------------------

    def signal_workorder_started(self, workorder_name: str, agent_name: str) -> None:
        """
        Signal that a workorder execution started.

        Called by queue-worker when agent starts working on a workorder.

        Args:
            workorder_name: Name of workorder
            agent_name: Which agent is working on it

        Stub: will record start time in Data, return None
        """
        print(f"stub in queue_worker_signal.py, QueueWorkerSignal.signal_workorder_started called by queue_worker returning None. actual method will do Data update with start timestamp and return None for <workorder_name: str, agent_name: str> input values")
        pass

    def signal_workorder_failed(self, workorder_name: str, agent_name: str, error_msg: str = "", exit_code: int = 1) -> None:
        """
        Signal that a workorder execution failed.

        Called by queue-worker when agent fails (non-zero exit or error).

        Args:
            workorder_name: Name of workorder
            agent_name: Which agent failed
            error_msg: Error message/output from agent
            exit_code: Exit code from agent subprocess

        Stub: will record failure in Data and trigger failure tracker, return None
        """
        print(f"stub in queue_worker_signal.py, QueueWorkerSignal.signal_workorder_failed called by queue_worker returning None. actual method will do Data update and call failure tracker, return None for <workorder_name: str, agent_name: str, error_msg: str, exit_code: int> input values")
        pass

    def signal_workorder_succeeded(self, workorder_name: str, agent_name: str) -> None:
        """
        Signal that a workorder execution succeeded.

        Called by queue-worker when agent finishes successfully.

        Args:
            workorder_name: Name of workorder
            agent_name: Which agent succeeded

        Stub: will record success in Data, move to done/, return None
        """
        print(f"stub in queue_worker_signal.py, QueueWorkerSignal.signal_workorder_succeeded called by queue_worker returning None. actual method will do Data update and workorder movement, return None for <workorder_name: str, agent_name: str> input values")
        pass

    def signal_workorder_progress(self, workorder_name: str, agent_name: str, progress: dict = None) -> None:
        """
        Heartbeat signal that workorder is still running (not hung).

        Called periodically by queue-worker while agent is running.

        Args:
            workorder_name: Name of workorder
            agent_name: Which agent is running
            progress: Optional progress dict (e.g., {"step": "...", "percent": 50})

        Stub: will update last_heartbeat_ts in Data, return None
        """
        print(f"stub in queue_worker_signal.py, QueueWorkerSignal.signal_workorder_progress called by queue_worker returning None. actual method will do Data update with heartbeat and return None for <workorder_name: str, agent_name: str, progress: dict|None> input values")
        pass

    # -----------------------------------------------------------------------
    # PM queries these signals
    # -----------------------------------------------------------------------

    def get_last_signal(self, workorder_name: str) -> dict:
        """
        Get last signal for a workorder.

        Returns: {
            "status": "started|failed|succeeded|progress",
            "agent": str,
            "ts": int (timestamp),
            "error_msg": str (if failed),
            "exit_code": int (if failed)
        } or None

        Stub: will read from Data storage, return signal dict
        """
        print(f"stub in queue_worker_signal.py, QueueWorkerSignal.get_last_signal called by pm_dispatcher returning None. actual method will do Data lookup and return <dict | None> for <workorder_name: str> input values")
        return None

    def clear_signals(self, workorder_name: str) -> None:
        """
        Clear signals for a workorder (when moving to new state).

        Stub: will delete entry from Data, return None
        """
        print(f"stub in queue_worker_signal.py, QueueWorkerSignal.clear_signals called by pm_dispatcher returning None. actual method will do Data cleanup and return None for <workorder_name: str> input values")
        pass
