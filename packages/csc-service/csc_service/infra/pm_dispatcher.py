"""
PM Dispatcher: Core routing and assignment logic.

Decides:
1. What workorder is next (from ready/)
2. Who should work it (which agent)
3. What to do if it fails (retry, switch agents, debug)

Uses:
- WorkorderFailureTracker for failure persistence
- WorkorderQueue for state management
- QueueWorkerSignal to receive failure reports
- Platform for cross-platform paths
"""

from pathlib import Path
from csc_service.shared.data import Data
from csc_service.shared.platform import Platform
from csc_service.shared.log import Log


class PMDispatcher(Data):
    """
    Project Manager Dispatcher.

    Core logic for routing workorders to agents and making retry decisions.
    Runs once per cycle in main.py's event loop.
    """

    def __init__(self):
        super().__init__()
        self.name = "pm_dispatcher"
        self.init_data("pm_dispatcher_state.json")
        self.platform = Platform()

    def run_cycle(self) -> dict:
        """
        Run one PM cycle: decide next workorder and assign to agent.

        Steps:
        1. Check queue-worker signals for failures
        2. Handle failures (retry, switch agent, escalate to debug)
        3. Check if any agent is busy (has queued work)
        4. If idle: pick next workorder from ready/
        5. Decide which agent should work it
        6. Create orders.md in agent's queue/in/
        7. Move workorder to wip/

        Returns: {
            "assigned": bool (did we assign something),
            "workorder": str (name) or None,
            "agent": str (name) or None,
            "decision": str (reason/explanation)
        }
        """
        result = {
            "assigned": False,
            "workorder": None,
            "agent": None,
            "decision": ""
        }

        # Check queue idle
        if not self._is_queue_idle():
            result["decision"] = "queue busy, waiting for current work to finish"
            return result

        # Pick next workorder
        workorder_name = self._pick_next_workorder()
        if not workorder_name:
            result["decision"] = "no workorders in ready/"
            return result

        # Choose agent
        agent_name = self._choose_agent(workorder_name)
        if not agent_name:
            result["decision"] = "no available agent"
            return result

        # Assign to agent
        if self._assign_to_agent(workorder_name, agent_name):
            result["assigned"] = True
            result["workorder"] = workorder_name
            result["agent"] = agent_name
            result["decision"] = f"assigned to {agent_name}"
        else:
            result["decision"] = f"failed to assign to {agent_name}"

        return result

    # -----------------------------------------------------------------------
    # Decision 1: Check for failures and handle them
    # -----------------------------------------------------------------------

    def _handle_failures(self) -> None:
        """
        Check queue-worker signals for failures, take action.

        Logic:
        - If failure: increment counter, decide action
        - At 10 failures: switch agents
        - At 20 failures: move to failed/, create debug workorder

        Stub: will process all pending failures, return None
        """
        print(f"stub in pm_dispatcher.py, PMDispatcher._handle_failures called by run_cycle returning None. actual method will do failure processing and escalation and return None for no input values")
        pass

    # -----------------------------------------------------------------------
    # Decision 2: Is queue idle?
    # -----------------------------------------------------------------------

    def _is_queue_idle(self) -> bool:
        """
        Check if all agents are idle (no work queued in queue/in or queue/work).

        Returns: bool (True if all agents idle)
        """
        # Scan agents/ directory for any agent with pending work
        agents_dir = self.platform.PROJECT_ROOT / "agents"
        if not agents_dir.exists():
            return True

        for agent_dir in agents_dir.iterdir():
            if not agent_dir.is_dir():
                continue
            # Check queue/in/ and queue/work/ for pending orders.md
            queue_in = agent_dir / "queue" / "in" / "orders.md"
            queue_work = agent_dir / "queue" / "work" / "orders.md"
            if queue_in.exists() or queue_work.exists():
                self.log(f"Agent {agent_dir.name} has pending work", "DEBUG")
                return False

        return True

    # -----------------------------------------------------------------------
    # Decision 3: Pick next workorder
    # -----------------------------------------------------------------------

    def _pick_next_workorder(self) -> str:
        """
        Pick next workorder from ready/.

        Priority: oldest first (highest priority) = lowest mtime

        Returns: workorder filename, or None if none available
        """
        ready_dir = self.platform.PROJECT_ROOT / "ops" / "wo" / "ready"
        if not ready_dir.exists():
            return None

        workorders = sorted(
            (f for f in ready_dir.iterdir() if f.is_file()),
            key=lambda f: f.stat().st_mtime
        )

        if not workorders:
            return None

        return workorders[0].name

    # -----------------------------------------------------------------------
    # Decision 4: Choose agent (routing logic)
    # -----------------------------------------------------------------------

    def _choose_agent(self, workorder_name: str) -> str:
        """
        Choose which agent should work on a workorder.

        Logic:
        1. Parse YAML frontmatter for 'agent:' preference
        2. Check priority (P0, P1 = high, P2/P3 = low)
        3. Cost optimization for low-priority:
           - If batch/remote eligible: use haiku (cheapest)
           - Otherwise: gemini-flash (cheap Gemini)
        4. High-priority: use best agents (gemini-pro first)
        5. Fallback: if preferred agent unavailable, use alternative

        Args: workorder_name
        Returns: agent name (e.g., "gemini-flash", "haiku", "sonnet")
        """
        ready_dir = self.platform.PROJECT_ROOT / "ops" / "wo" / "ready"
        workorder_path = ready_dir / workorder_name

        # Try to parse frontmatter
        frontmatter = self._parse_frontmatter(workorder_path)

        # If agent specified in frontmatter, use it
        if frontmatter.get("agent"):
            return frontmatter["agent"]

        # Default: use haiku for now (can be expanded with cost-aware logic)
        return "haiku"

    def _parse_frontmatter(self, workorder_path: Path) -> dict:
        """
        Parse YAML frontmatter from workorder file.

        Returns: {
            "agent": str or None,
            "priority": str ("P0", "P1", "P2", "P3"),
            "batch_eligible": bool,
            "role": str or None,
            "other_fields": {...}
        }
        """
        result = {
            "agent": None,
            "priority": "P2",
            "batch_eligible": False,
            "role": None
        }

        if not workorder_path.exists():
            return result

        try:
            content = workorder_path.read_text(encoding='utf-8')
            # Look for --- frontmatter markers
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 2:
                    fm_text = parts[1]
                    # Simple parsing: look for key: value lines
                    for line in fm_text.split("\n"):
                        line = line.strip()
                        if ":" in line:
                            key, val = line.split(":", 1)
                            key = key.strip().lower()
                            val = val.strip()
                            if key == "agent":
                                result["agent"] = val
                            elif key == "priority":
                                result["priority"] = val
                            elif key == "batch_eligible":
                                result["batch_eligible"] = val.lower() in ["true", "yes", "1"]
                            elif key == "role":
                                result["role"] = val
        except Exception as e:
            self.log(f"Could not parse frontmatter: {e}", "DEBUG")

        return result

    # -----------------------------------------------------------------------
    # Decision 5: Assign to agent
    # -----------------------------------------------------------------------

    def _assign_to_agent(self, workorder_name: str, agent_name: str) -> bool:
        """
        Assign workorder to agent.

        Steps:
        1. Move workorder from ready/ to wip/
        2. Create orders.md in agents/AGENT/queue/in/
        3. Update Data with assignment info
        4. Clear failure count (fresh start)

        Args:
            workorder_name: Name of workorder
            agent_name: Agent to assign to

        Returns: bool (success)
        """
        try:
            ready_dir = self.platform.PROJECT_ROOT / "ops" / "wo" / "ready"
            wip_dir = self.platform.PROJECT_ROOT / "ops" / "wo" / "wip"

            src = ready_dir / workorder_name
            dst = wip_dir / workorder_name

            if not src.exists():
                self.log(f"Workorder not found: {src}", "WARN")
                return False

            wip_dir.mkdir(parents=True, exist_ok=True)
            src.rename(dst)
            self.log(f"Moved {workorder_name} to wip/")

            # Create orders.md in agent's queue/in/
            success = self._create_agent_orders(workorder_name, agent_name, dst)
            if not success:
                # Rollback: move back to ready/
                dst.rename(src)
                return False

            self.log(f"Assigned {workorder_name} to {agent_name}")
            return True

        except Exception as e:
            self.log(f"Error assigning workorder: {e}", "ERROR")
            return False

    def _create_agent_orders(self, workorder_name: str, agent_name: str, workorder_path: Path) -> bool:
        """
        Create orders.md in agent's queue/in/ directory.

        Format:
        ```
        # Assignment
        Workorder: <workorder_name>
        Agent: <agent_name>
        Timestamp: <ISO timestamp>
        ...
        ```

        Args:
            workorder_name: Name of workorder
            agent_name: Which agent
            workorder_path: Path to workorder file in wip/

        Returns: bool (success)
        """
        try:
            from datetime import datetime
            import shutil

            queue_in = self.platform.PROJECT_ROOT / "ops" / "agents" / agent_name / "queue" / "in"
            queue_in.mkdir(parents=True, exist_ok=True)

            orders_path = queue_in / "orders.md"

            # Create orders.md with assignment details
            # Format: must include relative path like ops/wo/wip/WORKORDER_NAME for queue-worker to find it
            timestamp = datetime.now().isoformat()
            rel_path = f"ops/wo/wip/{workorder_name}"
            content = f"""# Assignment

Workorder: {workorder_name}
Agent: {agent_name}
Timestamp: {timestamp}
Path: {rel_path}

---

{workorder_path.read_text(encoding='utf-8', errors='ignore')[:500]}...
"""

            orders_path.write_text(content, encoding='utf-8')
            self.log(f"Created orders.md for {agent_name}")
            return True

        except Exception as e:
            self.log(f"Error creating agent orders: {e}", "ERROR")
            return False

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def log(self, msg: str, level: str = "INFO") -> None:
        """
        Log message (inherited from Data -> Log).
        """
        # Call parent Log.log() method
        from csc_service.shared.log import Log
        Log.log(self, msg, level)
