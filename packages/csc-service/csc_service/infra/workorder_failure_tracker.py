"""
Workorder Failure Tracking using Data persistence.

Tracks how many times each workorder has failed, by which agents,
and manages escalation to debug agent after thresholds.

Uses Data.get_data/put_data for persistent storage of failure counts.
"""

from csc_service.shared.data import Data


class WorkorderFailureTracker(Data):
    """
    Tracks failures per workorder using persistent Data storage.

    Decisions:
    - After 10 failures with one agent: switch to different agent
    - After 20 total failures: move to failed/ and create debug workorder

    Storage format (in default data.json):
        {
            "workorder_failures": {
                "improve_test_coverage.md": {
                    "total_count": 15,
                    "attempts": [
                        {"agent": "gemini-flash", "count": 10},
                        {"agent": "gemini-pro", "count": 5}
                    ],
                    "last_failure_ts": 1710799200,
                    "last_error": "..."
                }
            }
        }
    """

    # Thresholds
    FAILURES_PER_AGENT = 10
    FAILURES_TOTAL = 20

    def __init__(self):
        super().__init__()
        self.name = "workorder_failure_tracker"
        self.init_data("workorder_failures.json")

    def record_failure(self, workorder_name: str, agent_name: str, error_msg: str = "") -> dict:
        """
        Record a failure for a workorder by an agent.

        Returns: {"total": int, "agent_count": int, "should_switch": bool, "should_escalate": bool}

        Stub: will do full failure tracking with persistence, return decision flags
        """
        print(f"stub in workorder_failure_tracker.py, WorkorderFailureTracker.record_failure called by queue_worker returning {{'total': 0, 'agent_count': 0, 'should_switch': False, 'should_escalate': False}}. actual method will do failure tracking with persistence and return decision flags for <should_switch: bool, should_escalate: bool> for <workorder_name: str, agent_name: str> input values")
        return {
            "total": 0,
            "agent_count": 0,
            "should_switch": False,
            "should_escalate": False
        }

    def get_failure_count(self, workorder_name: str, agent_name: str = None) -> int:
        """
        Get total or agent-specific failure count for workorder.

        Args:
            workorder_name: Name of workorder
            agent_name: Optional agent name. If None, return total count.

        Returns: int (failure count, 0 if not found)

        Stub: will read from Data storage, return count
        """
        print(f"stub in workorder_failure_tracker.py, WorkorderFailureTracker.get_failure_count called by pm_dispatcher returning 0. actual method will do Data storage lookup and return count for <workorder_name: str, agent_name: str|None> input values")
        return 0

    def clear_failures(self, workorder_name: str) -> None:
        """
        Clear failure tracking for a workorder (when it succeeds).

        Stub: will delete entry from Data storage
        """
        print(f"stub in workorder_failure_tracker.py, WorkorderFailureTracker.clear_failures called by queue_worker returning None. actual method will do Data storage cleanup and return None for <workorder_name: str> input values")
        pass

    def get_alternate_agent(self, current_agent: str) -> str:
        """
        Pick a different agent at same capability level for retry.

        Strategy: Don't escalate to better model, just try different one.
        - gemini-flash ↔ gemini-pro
        - haiku ↔ gemini-flash

        Args: current_agent (name of agent that just failed)
        Returns: str (different agent name to try next)

        Stub: will implement agent rotation logic, return alternative
        """
        print(f"stub in workorder_failure_tracker.py, WorkorderFailureTracker.get_alternate_agent called by pm_dispatcher returning 'haiku'. actual method will do agent rotation at same capability level and return <agent_name: str> for <current_agent: str> input values")
        return "haiku"

    def should_create_debug_workorder(self, workorder_name: str) -> bool:
        """
        Check if workorder has hit escalation threshold for debug agent.

        Returns: True if total failures >= FAILURES_TOTAL

        Stub: will check Data storage, return boolean
        """
        print(f"stub in workorder_failure_tracker.py, WorkorderFailureTracker.should_create_debug_workorder called by pm_dispatcher returning False. actual method will do threshold check and return <bool> for <workorder_name: str> input values")
        return False

    def get_failure_history(self, workorder_name: str) -> dict:
        """
        Get complete failure history for a workorder.

        Returns: {
            "total": int,
            "attempts": [{"agent": str, "count": int}, ...],
            "last_failure_ts": int,
            "last_error": str
        }

        Stub: will read from Data storage, return full history
        """
        print(f"stub in workorder_failure_tracker.py, WorkorderFailureTracker.get_failure_history called by debug_agent returning {{'total': 0, 'attempts': [], 'last_failure_ts': 0, 'last_error': ''}}. actual method will do Data storage lookup and return <history: dict> for <workorder_name: str> input values")
        return {
            "total": 0,
            "attempts": [],
            "last_failure_ts": 0,
            "last_error": ""
        }
