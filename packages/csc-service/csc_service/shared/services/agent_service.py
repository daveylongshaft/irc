import os
import sys
import signal
import shutil
import subprocess
import time
import json
from pathlib import Path
from datetime import datetime
from csc_service.server.service import Service
from csc_service.shared.utils import QueueDirectories, WIPJournal
from csc_service.shared.platform import Platform
from csc_service.shared.services import PROJECT_ROOT as _PROJECT_ROOT


class agent( Service ):
    """AI agent runner service.

    Spawns a non-interactive AI CLI session to work a prompt file,
    following the ready/wip/done workflow with journaling.

    Commands:
      list                    - List available AI agent backends.
      select <name>           - Select which agent to use.
      assign <prompt_file>    - Assign a prompt to the selected agent.
      status                  - Show running agent status.
      stop                    - Stop the running agent.
      kill                    - Kill agent, move WIP back to ready.
      tail [N]                - Tail N lines of WIP journal (default 20).
    """

    PROJECT_ROOT = Platform.PROJECT_ROOT
    WORKORDERS_BASE = Platform.get_wo_dir()
    LOGS_DIR = Platform.get_logs_dir()

    @property
    def PROMPTS_BASE(self):
        return self.WORKORDERS_BASE

    @property
    def READY_DIR(self):
        return self.WORKORDERS_BASE / "ready"

    @property
    def WIP_DIR(self):
        return self.WORKORDERS_BASE / "wip"

    @property
    def DONE_DIR(self):
        return self.WORKORDERS_BASE / "done"

    # System-level enforcement prompt injected via --append-system-prompt (claude)
    # This is separate from the user prompt and cannot be scrolled past.
    WIP_SYSTEM_PROMPT = (
        "MANDATORY: Journal every step to the WIP file BEFORE doing it. "
        "Run: echo '<what you are about to do>' >> workorders/wip/{wip_file} "
        "BEFORE each action. No checkboxes. No Edit tool. Just echo one line per step. "
        "Example: echo 'read version_service.py' >> workorders/wip/{wip_file} "
        "NEVER run tests — cron handles that within 1 minute for free. "
        "NEVER DELETE WIP FILES. The wrapper handles moving them to done/. "
        "NEVER run git commands. The wrapper handles git operations. "
        "When done, write COMPLETE to the WIP file and exit. "
        "If you do not update the WIP file, your work cannot be monitored or recovered. "
        "This is NON-NEGOTIABLE."
    )

    # Agent backends: all use cagent exec with per-agent YAML configs
    # Each agent dir has agents/<name>/cagent.yaml defining provider + model
    KNOWN_AGENTS = {
        "claude":              {"label": "Claude Haiku 4.5 (default)"},
        "claude-batch":        {"label": "Claude Batch via queue-worker (isolated repo)"},
        "haiku":               {"label": "Claude Haiku 4.5 (fast, cheap)"},
        "sonnet":              {"label": "Claude Sonnet 4.6 (balanced, capable)"},
        "opus":                {"label": "Claude Opus 4.6 (smartest)"},
        "gemini":              {"label": "Gemini 2.5 Pro (default)"},
        "gemini-2.5-pro":      {"label": "Gemini 2.5 Pro (smartest)"},
        "gemini-2.5-flash":    {"label": "Gemini 2.5 Flash (fast, cheap)"},
        "gemini-2.5-flash-lite": {"label": "Gemini 2.5 Flash Lite (fastest, cheapest)"},
        "gemini-3-flash-preview": {"label": "Gemini 3 Flash Preview (fast, cheap)"},
        "gemini-3-pro":        {"label": "Gemini 3 Pro (smartest)"},
        "chatgpt":             {"label": "ChatGPT 4o (smartest)"},
        "qwen":                {"label": "Qwen 3 (local, free)"},
        "deepseek":            {"label": "DeepSeek R1 (local, free)"},
        "codellama":           {"label": "Llama 3.1 (local, free)"},
    }

    # Stale watchdog: if WIP file unchanged for this many seconds, log a warning
    STALE_THRESHOLD_SECS = 300  # 5 minutes

    # Docker Model Runner endpoint for local models
    DMR_ENDPOINT = "http://localhost:12434/engines/v1"
    LOCAL_AGENTS = {"qwen", "deepseek", "codellama"}

    def _build_cmd(self, agent_name, prompt, wip_filename, repo_clone_path=None):
        """Build the command for the given agent.
        Returns (cmd_list, env_dict).
        """
        cfg = self.KNOWN_AGENTS.get(agent_name)
        if not cfg:
            return [], None

        sys_prompt = self.WIP_SYSTEM_PROMPT.format(wip_file=wip_filename)
        full_prompt = f"SYSTEM RULE: {sys_prompt}\n\n{prompt}"

        # Determine working directory (use temp clone if available, otherwise main repo)
        working_dir = str(self.PROJECT_ROOT)
        if not repo_clone_path:
            try:
                platform = Platform()
                agent_work_base = platform.agent_work_base
                if agent_work_base:
                    repo_clone_path = agent_work_base / agent_name / "repo"
            except Exception:
                pass
        if repo_clone_path:
            working_dir = str(repo_clone_path)

        # Build environment variables
        env = os.environ.copy()
        if repo_clone_path:
            agent_work_dir = Path(repo_clone_path).parent
            env["CSC_AGENT_WORK"] = str(agent_work_dir)
            env["CSC_AGENT_REPO"] = str(repo_clone_path)
            env["CSC_AGENT_HOME"] = str(agent_work_dir)

        try:
            platform = Platform()
            if platform.agent_temp_root:
                env["CSC_TEMP_ROOT"] = str(platform.agent_temp_root)
        except Exception:
            pass

        agents_dir = Platform.get_agents_dir()
        if agent_name in self.LOCAL_AGENTS:
            # Local agents use cagent exec with cagent.yaml
            yaml_path = agents_dir / agent_name / "cagent.yaml"
            if not yaml_path.exists():
                self.log(f"ERROR: cagent.yaml not found for local agent {agent_name} at {yaml_path}")
                return [], None
            
            cmd = [
                "cagent", "exec",
                str(yaml_path),
                full_prompt,
                "--working-dir", working_dir,
                "--env-from-file", str(self.PROJECT_ROOT / ".env"),
            ]
            env.setdefault("OPENAI_BASE_URL", self.DMR_ENDPOINT)
            env.setdefault("OPENAI_API_KEY", "dummy")
        else:
            # Remote agents use run_agent.sh or run_agent.bat
            run_script_sh = agents_dir / agent_name / "bin" / "run_agent.sh"
            run_script_bat = agents_dir / agent_name / "bin" / "run_agent.bat"
            
            run_script = None
            if run_script_sh.exists():
                run_script = run_script_sh
            elif run_script_bat.exists():
                run_script = run_script_bat

            if not run_script:
                self.log(f"ERROR: run_agent script not found for remote agent {agent_name} in {agents_dir / agent_name / 'bin'}")
                return [], None
            
            if run_script.suffix == ".sh":
                cmd = ["bash", str(run_script), full_prompt, str(self.WIP_DIR / wip_filename)]
            else: # .bat
                cmd = [str(run_script), full_prompt, str(self.WIP_DIR / wip_filename)]
            
            # For remote agents, working_dir should typically be the agent's root to find its resources
            working_dir = str(agents_dir / agent_name)

        return cmd, env

    def __init__(self, server_instance):
        super().__init__( server_instance )
        self.name = "agent"
        self.init_data()
        self.LOGS_DIR.mkdir( parents=True, exist_ok=True )
        self.queue = QueueDirectories(self.PROMPTS_BASE)

        # Ensure defaults in data store
        if self.get_data( "selected_agent" ) is None or self.get_data( "selected_agent" ) not in self.KNOWN_AGENTS:
            self.put_data( "selected_agent", "haiku" )
        if self.get_data( "current_pid" ) is None:
            self.put_data( "current_pid", None, flush=False )
            self.put_data( "current_prompt", None, flush=False )
            self.put_data( "current_log", None, flush=False )
            self.put_data( "started_at", None )

        self.log( "Agent service initialized." )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _is_running(self):
        """Check if the tracked agent process is still alive."""
        pid = self.get_data( "current_pid" )
        if pid is None:
            return False
        try:
            os.kill( pid, 0 )
            return True
        except (OSError, ProcessLookupError):
            return False

    def _find_prompt(self, filename):
        """Find a prompt file in ready/ or wip/. Returns Path or None."""
        filepath, _ = self.queue.find_file(filename, add_suffix=True)
        return filepath

    @staticmethod
    def _read_text_safe(path):
        """Read a text file, trying utf-8 first then falling back to latin-1."""
        try:
            return path.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            return path.read_text(encoding='latin-1')

    def _create_queue_metadata(self, agent_name: str, workorder_name: str, original_path: Path) -> dict:
        """Create metadata dictionary for a queued workorder.

        Args:
            agent_name: The name of the agent assigned to the workorder.
            workorder_name: The filename of the workorder (e.g., PROMPT_fix_bug.md).
            original_path: The original full path of the prompt file before being moved to WIP.

        Returns:
            A dictionary containing timestamp, agent_name, workorder_name,
            original_prompt_path, and platform_paths.
        """
        now_utc = datetime.utcnow().isoformat(timespec='seconds') + 'Z'
        platform_instance = Platform()
        
        # Get platform paths from platform.json
        platform_paths = {}
        try:
            pdata = Platform.load_platform_json()
            platform_paths = pdata.get("runtime", {})
        except Exception as e:
            self.log(f"WARNING: Could not retrieve platform paths for metadata: {e}")

        metadata = {
            "timestamp": now_utc,
            "agent_name": agent_name,
            "workorder_name": workorder_name,
            "original_prompt_path": str(original_path),
            "platform_paths": platform_paths,
        }
        return metadata

    def _ensure_agent_dirs(self, agent_dir, agent_name):
        """Create agent directory structure and copy default template if missing."""
        for subdir in ["bin", "queue/in", "queue/work", "queue/out", "context"]:
            (agent_dir / subdir).mkdir(parents=True, exist_ok=True)
        # Copy default template if no agent-specific one exists
        template_dst = agent_dir / "orders.md-template"
        if not template_dst.exists():
            default_tmpl = Platform.get_agents_dir() / "templates" / "default.md"
            if default_tmpl.exists():
                import shutil as _shutil
                _shutil.copy2(str(default_tmpl), str(template_dst))
        self.log(f"Created agent directory structure for '{agent_name}'")

    def _detect_agents(self):
        """Return dict of agent name -> available (bool).
        An agent is available if its requirements are met (cagent.yaml for local, run_agent script for remote).
        """
        has_cagent = shutil.which("cagent") is not None
        result = {}
        agents_dir = Platform.get_agents_dir()
        for name in self.KNOWN_AGENTS:
            if name in self.LOCAL_AGENTS:
                # Local agents still use cagent.yaml
                yaml_path = agents_dir / name / "cagent.yaml"
                result[name] = has_cagent and yaml_path.exists()
            else:
                # Remote agents use run_agent scripts
                run_script_sh = agents_dir / name / "bin" / "run_agent.sh"
                run_script_bat = agents_dir / name / "bin" / "run_agent.bat"
                result[name] = run_script_sh.exists() or run_script_bat.exists()
        return result

    # ------------------------------------------------------------------
    # Capability-tagged prompt support
    # ------------------------------------------------------------------



    @staticmethod
    def _parse_front_matter(filepath):
        """Parse YAML-like front-matter from a prompt file.

        Supports format:
            ---
            requires: [docker, git, python3]
            platform: [linux]
            min_ram: 2GB
            ---

        Returns dict of parsed tags, or empty dict if no front-matter.
        """
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
        except (OSError, UnicodeDecodeError):
            return {}

        # Check for front-matter delimiters
        if not content.startswith("---"):
            return {}

        # Find closing ---
        end = content.find("---", 3)
        if end == -1:
            return {}

        front = content[3:end].strip()
        tags = {}

        for line in front.split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            key = key.strip().lower()
            value = value.strip()

            # Parse list values: [a, b, c]
            if value.startswith("[") and value.endswith("]"):
                items = [item.strip().strip("'\"") for item in value[1:-1].split(",")]
                tags[key] = [i for i in items if i]
            else:
                tags[key] = value.strip("'\"")

        return tags

    def _check_prompt_capabilities(self, filepath):
        """Check if this system can satisfy a prompt's requirements.

        Returns (can_run: bool, reasons: list[str], tags: dict).
        """
        tags = self._parse_front_matter(filepath)
        if not tags:
            return True, [], tags

        # Load platform data
        platform_data = Platform.load_platform_json()
        if not platform_data:
            # No platform data available, allow it
            return True, [], tags

        reasons = []

        # Check required tools
        requires = tags.get("requires", [])
        if isinstance(requires, str):
            requires = [requires]
        for tool in requires:
            tool_lower = tool.lower()
            if tool_lower == "docker":
                docker = platform_data.get("docker", {})
                if not docker.get("usable"):
                    reasons.append(f"Docker not available")
            else:
                software = platform_data.get("software", {})
                agents = platform_data.get("ai_agents", {})
                sw_info = software.get(tool_lower, {})
                ag_info = agents.get(tool_lower, {})
                if not sw_info.get("installed") and not ag_info.get("installed"):
                    reasons.append(f"Tool '{tool}' not installed")

        # Check platform
        platform_req = tags.get("platform", [])
        if isinstance(platform_req, str):
            platform_req = [platform_req]
        if platform_req:
            os_info = platform_data.get("os", {})
            system = os_info.get("system", "").lower()
            plat = os_info.get("platform", "").lower()
            matched = any(r.lower() in (system, plat) for r in platform_req)
            if not matched:
                reasons.append(f"Platform mismatch: need {platform_req}, have {system}")

        # Check min RAM
        min_ram = tags.get("min_ram")
        if min_ram:
            from csc_service.shared.platform import _parse_size
            required = _parse_size(min_ram)
            hw = platform_data.get("hardware", {})
            available = hw.get("ram_total_mb", 0) * 1024 * 1024
            if available < required:
                reasons.append(f"Insufficient RAM: need {min_ram}, have {hw.get('ram_total_mb', 0)}MB")

        return len(reasons) == 0, reasons, tags

    # Per-backend context files (performance reviews, tips)
    AGENT_CONTEXT_FILES = {
        "gemini": "tools/gemini_context.md",
        "coding-agent": "AIDER.md",
    }

    def _build_prompt(self, wip_path):
        """Assemble the full prompt from README.1shot + agent context dir + WIP content."""
        selected = self.get_data( "selected_agent" ) or "haiku"
        parts = []

        # 1. README.1shot (one-shot focused agent instructions)
        readme_1shot = self.PROJECT_ROOT / "README.1shot"
        if readme_1shot.exists():
            parts.append( f"=== README.1shot ===\n{readme_1shot.read_text( encoding='utf-8' )}" )

        # 2. Agent context directory (agents/<name>/context/*.md)
        ctx_dir = self.PROJECT_ROOT / "ops" / "agents" / selected / "context"
        if ctx_dir.exists():
            for f in sorted( ctx_dir.glob( "*.md" ) ):
                parts.append( f"=== {f.name} ===\n{f.read_text( encoding='utf-8' )}" )

        # 3. Legacy per-backend context files (fallback)
        if not ctx_dir.exists():
            cfg = self.KNOWN_AGENTS.get( selected, {} )
            backend = cfg.get( "binary", "" )
            context_rel = self.AGENT_CONTEXT_FILES.get( backend )
            if context_rel:
                context_path = self.PROJECT_ROOT / context_rel
                if context_path.exists():
                    parts.append( f"=== Agent Context ({backend}) ===\n{context_path.read_text( encoding='utf-8' )}" )

        # 4. WIP file contents
        parts.append( f"=== WIP: {wip_path.name} ===\n{wip_path.read_text( encoding='utf-8' )}" )

        return "\n\n".join( parts )

    # ------------------------------------------------------------------
    # Service commands
    # ------------------------------------------------------------------

    def list(self) -> str:
        """List available AI agent backends."""
        agents = self._detect_agents()
        selected = self.get_data( "selected_agent" )
        lines = ["Available agents:"]
        for name, available in agents.items():
            cfg = self.KNOWN_AGENTS[name]
            status = "OK" if available else "NOT FOUND"
            marker = " <-- selected" if name == selected else ""
            lines.append( f"  {name}: {cfg['label']} [{status}]{marker}" )
        return "\n".join( lines )

    def select(self, name: str) -> str:
        """Select which AI agent backend to use."""
        name = name.lower().strip()
        if name not in self.KNOWN_AGENTS:
            return f"Unknown agent '{name}'. Known: {', '.join( self.KNOWN_AGENTS.keys() )}"
        agents = self._detect_agents()
        if not agents.get( name ):
            return f"Agent '{name}' is not installed (binary not found in PATH)."
        self.put_data( "selected_agent", name )
        return f"Selected agent: {name}"



    def assign(self, prompt_filename: str) -> str:
        """Assign a prompt to the selected agent for queue-based processing.

        This method moves the prompt from its source location (ready/ or wip/)
        to a new WIP location, creates associated metadata, and places both
        in the target agent's queue/in/ directory for the queue worker to pick up.

        Args:
            prompt_filename: The name of the prompt file (e.g., Q01_analysis.md).

        Returns:
            A status string indicating success or failure.
        """
        # Find the workorder in ready/ or wip/
        # prompt_path is the original location
        prompt_path = self._find_prompt(prompt_filename)
        if prompt_path is None:
            return f"Workorder not found in ready/ or wip/: {prompt_filename}"

        # Check platform capabilities
        can_run, reasons, tags = self._check_prompt_capabilities(prompt_path)
        if not can_run:
            reason_str = "; ".join(reasons)
            self.log(f"Workorder '{prompt_filename}' skipped: {reason_str}")
            return (
                f"Cannot assign '{prompt_filename}' — system lacks required capabilities:\n"
                f"  {reason_str}\n"
                "Workorder left in ready/ for a capable system to pick up."
            )

        # Get selected agent
        selected = self.get_data("selected_agent") or "haiku"
        agent_dir = self.PROJECT_ROOT / "ops" / "agents" / selected
        
        # Ensure agent directory structure (including queue/in, queue/work, queue/out)
        # This calls _ensure_agent_dirs
        if not agent_dir.exists():
            self._ensure_agent_dirs(agent_dir, selected)

        # Keep original filename when moving to WIP (no timestamping)
        wip_filename = prompt_path.name

        # Construct the full path for the new WIP file in workorders/wip/
        wip_full_path = self.WIP_DIR / wip_filename

        try:
            # Move the original prompt file to the new WIP location
            shutil.move(str(prompt_path), str(wip_full_path))
            self.log(f"Moved '{prompt_path.name}' to '{wip_full_path.name}'")
            
            # Create metadata for the workorder
            metadata = self._create_queue_metadata(selected, wip_filename, prompt_path)

            # Write ONLY the metadata to the agent's queue/in/ (for tracking)
            # The actual workorder content is already in WIP_DIR and referenced by orders.md
            metadata_filename = f"{Path(wip_filename).stem}.json"
            queue_in_path = Platform.get_agent_queue_dir(selected, "in")
            queue_in_path.mkdir(parents=True, exist_ok=True)
            metadata_content = json.dumps(metadata, indent=4)
            self._write_text_file(queue_in_path / metadata_filename, metadata_content)

            # Generate orders.md from template via script
            # This script creates queue/in/orders.md which points to the WIP file
            self._run_generate_orders_md_script(selected, wip_filename)

            self.log(f"Queued '{wip_filename}' for {selected}")
            return f"Queued '{wip_filename}' for agent '{selected}'."
        except Exception as e:
            self.log(f"Failed to assign workorder {prompt_filename} for {selected}: {e}")
            # Attempt to move the WIP file back to ready/ if an error occurred after moving it
            if wip_full_path.exists() and prompt_path.parent != self.READY_DIR:
                try:
                    shutil.move(str(wip_full_path), str(self.READY_DIR / prompt_path.name))
                    self.log(f"ERROR: Rolled back '{wip_full_path.name}' to ready/ due to failure.")
                except Exception as rollback_e:
                    self.log(f"CRITICAL ERROR: Failed to rollback '{wip_full_path.name}': {rollback_e}")
            return f"Failed to assign workorder: {e}"

    def _write_queued_files(self, wip_path: Path, metadata: dict, agent_name: str, workorder_filename: str):
        """Writes the workorder content and its metadata to the agent's queue/in/ directory.

        Args:
            wip_path: The full path to the WIP file containing the workorder content.
            metadata: The metadata dictionary for the workorder.
            agent_name: The name of the agent assigned to the workorder.
            workorder_filename: The unique filename for the workorder (e.g., Q01_analysis_timestamp.md).
        """
        queue_in_path = Platform.get_agent_queue_dir(agent_name, "in")

        # Ensure queue directories exist (already handled by _ensure_agent_dirs earlier, but good to be explicit)
        if not queue_in_path.exists():
            queue_in_path.mkdir(parents=True, exist_ok=True)

        # Read content from the WIP file
        workorder_content = self._read_text_safe(wip_path)

        # Write the workorder content to the agent's queue/in/ via Data() I/O
        self._write_text_file(queue_in_path / workorder_filename, workorder_content)
        self.log(f"Wrote queued workorder file: {queue_in_path / workorder_filename}")

        # Write the metadata to the agent's queue/in/ via Data() I/O
        metadata_filename = f"{Path(workorder_filename).stem}.json"
        metadata_content = json.dumps(metadata, indent=4)
        self._write_text_file(queue_in_path / metadata_filename, metadata_content)
        self.log(f"Wrote queued workorder metadata: {queue_in_path / metadata_filename}")

    def _run_generate_orders_md_script(self, agent_name: str, workorder_filename: str):
        """Generate orders.md in agent's queue/in/ with cached context.

        Generates stable context files from tools/ (based on .lastrun), then
        concatenates them with pathspecs and the workorder for prompt caching.

        Strategy:
        - Context files (standards, role, p-files, tree, tools/*) are stable
          and generated once (regenerated only when tools change)
        - Subsequent workorders reuse cached context, saving 90% on input tokens
        - No journaling instructions (agents run non-interactively)

        Files included (in volatility order — least changing first):
            00-standards.md        (STATIC)
            01-role.md             (STATIC)
            02-p-files.md          (SEMI-STABLE)
            03-tree.md             (SEMI-STABLE)
            04-tools-shared.md     (VOLATILE)
            05-tools-service.md    (VOLATILE)
            06-tools-server.md     (VOLATILE)
            07-tools-index.md      (MOST VOLATILE)

        Then:
            WORKORDER CONTENT
        """
        try:
            agent_dir = Platform.get_agents_dir() / agent_name
            context_dir = Platform.get_agent_context_dir(agent_name)
            queue_in_dir = Platform.get_agent_queue_dir(agent_name, "in")

            # Step 1: Refresh context files if tools changed
            lastrun_file = Platform.get_tools_lastrun_file()
            should_regenerate = True

            if context_dir.exists():
                # Check if any context file is older than tools/.lastrun
                context_files = list(context_dir.glob("*.md"))
                if context_files and lastrun_file.exists():
                    oldest_ctx = min(f.stat().st_mtime for f in context_files)
                    lastrun_time = lastrun_file.stat().st_mtime
                    should_regenerate = oldest_ctx < lastrun_time

            if should_regenerate:
                context_dir.mkdir(parents=True, exist_ok=True)

                # Copy/generate context files from tools/ (ordered by volatility)
                context_mappings = [
                    ("00-standards.md", Platform.PROJECT_ROOT / "ops" / "standards.md"),
                    ("01-role.md", Platform.get_roles_dir("_shared") / "README.md"),
                    ("02-p-files.md", Platform.PROJECT_ROOT / "p-files.list"),
                    ("03-tree.md", Platform.PROJECT_ROOT / "tree.txt"),
                    ("04-tools-shared.md", Platform.get_tools_dir() / "csc-shared.txt"),
                    ("05-tools-service.md", Platform.get_tools_dir() / "csc-service.txt"),
                    ("06-tools-server.md", Platform.get_tools_dir() / "server.txt"),
                    ("07-tools-index.md", Platform.get_tools_dir() / "INDEX.txt"),
                ]

                for ctx_name, src_path in context_mappings:
                    if src_path.exists():
                        content = self._read_text_file(src_path)
                        if content.strip():
                            self._write_text_file(context_dir / ctx_name, content)
                            self.log(f"Updated context: {ctx_name}")

            # Step 2: Concatenate context files + pathspecs + workorder
            orders_content = ""

            # Add all context files in order (cached on subsequent WOs)
            for ctx_file in sorted(context_dir.glob("*.md")):
                content = self._read_text_file(ctx_file)
                if content.strip():
                    orders_content += content + "\n\n"

            # Add pathspecs (NOT full contents — let agent read if needed)
            # Use Platform methods for cross-platform path handling
            plat = Platform()
            wip_path_rel = "ops/wo/wip/" + workorder_filename  # Already forward-slash safe
            wip_path_abs = plat.get_abs_root_path_forward_slashes(["ops", "wo", "wip", workorder_filename])

            orders_content += f"""
## YOUR ASSIGNMENT

- **Workorder file** (relative): {wip_path_rel}
- **Workorder file** (absolute): {wip_path_abs}
- **Work directory**: CSC_ROOT (project root)
- **Code clone**: tmp/clones/<agent>/<wo>-<ts>/repo/

Read your task from the workorder file. Journal progress using the API.
When complete, write "COMPLETE" to the workorder and exit.

---

"""

            # Add the actual workorder content
            wip_content = self._read_text_file(self.WIP_DIR / workorder_filename)
            if wip_content.strip():
                orders_content += f"## TASK\n\n{wip_content}"
            else:
                self.log(f"WARNING: WIP file is empty: {self.WIP_DIR / workorder_filename}")
                orders_content += "## TASK\n\n(workorder content not found)\n"

            # Step 3: Write orders.md to queue/in
            queue_in_dir.mkdir(parents=True, exist_ok=True)
            orders_path = queue_in_dir / "orders.md"
            self._write_text_file(orders_path, orders_content)
            self.log(f"Generated orders.md for {agent_name} ({len(orders_content)} chars, {len(orders_content.split())} words)")

        except Exception as e:
            self.log(f"ERROR: Failed to generate orders.md: {e}", "ERROR")
            import traceback
            self.log(traceback.format_exc(), "ERROR")

    def _format_elapsed(self, started):
        """Format elapsed time from a start timestamp."""
        if not started:
            return "?"
        secs = int( time.time() ) - started
        mins, s = divmod( secs, 60 )
        hrs, m = divmod( mins, 60 )
        if hrs:
            return f"{hrs}h {m}m {s}s"
        elif m:
            return f"{m}m {s}s"
        return f"{s}s"

    def _get_proc_mem(self, pid):
        """Get resident memory of a process in MB from /proc. Returns str or '?'."""
        try:
            with open( f"/proc/{pid}/status", 'r' ) as f:
                for line in f:
                    if line.startswith( "VmRSS:" ):
                        kb = int( line.split()[1] )
                        return f"{kb / 1024:.1f} MB"
        except (OSError, ValueError, IndexError):
            pass
        return "?"

    def _get_log_size(self, log_path):
        """Get log file size as human-readable string."""
        try:
            size = os.path.getsize( log_path )
            if size < 1024:
                return f"{size} B"
            elif size < 1024 * 1024:
                return f"{size / 1024:.1f} KB"
            return f"{size / (1024 * 1024):.1f} MB"
        except OSError:
            return "?"

    def _get_wip_progress(self, prompt_name):
        """Count completed/next/pending steps in WIP file."""
        wip_path = self.WIP_DIR / prompt_name
        if not wip_path.exists():
            return None
        try:
            content = wip_path.read_text( encoding='utf-8' )
            done = content.count( "[X]" )
            nexts = content.count( "[NEXT]" )
            pending = content.count( "[ ]" )
            lines = len( content.splitlines() )
            return {"done": done, "next": nexts, "pending": pending, "lines": lines}
        except OSError:
            return None

    def status(self) -> str:
        """Show queue and agent status by scanning queue directories and WIP files."""
        lines = []
        agents_dir = Platform.get_agents_dir()

        # Scan queue/work/ for running tasks
        running_tasks = []
        for agent_dir in sorted(agents_dir.iterdir()):
            if not agent_dir.is_dir():
                continue
            work_dir = agent_dir / "queue" / "work"
            if not work_dir.exists():
                continue
            agent_name = agent_dir.name
            for pid_file in work_dir.glob("*.pid"):
                prompt = pid_file.name[:-4]
                try:
                    pid = int(pid_file.read_text(encoding='utf-8').strip())
                    alive = self._is_running_pid(pid)
                except Exception:
                    pid = 0
                    alive = False
                running_tasks.append((agent_name, prompt, pid, alive))

        # Scan queue/in/ for pending tasks
        pending_tasks = []
        for agent_dir in sorted(agents_dir.iterdir()):
            if not agent_dir.is_dir():
                continue
            in_dir = agent_dir / "queue" / "in"
            if not in_dir.exists():
                continue
            agent_name = agent_dir.name
            for f in sorted(in_dir.glob("*.md")):
                pending_tasks.append((agent_name, f.name))

        # Show running tasks from queue
        if running_tasks:
            lines.append("Running (from queue):")
            for agent_name, prompt, pid, alive in running_tasks:
                state = "RUNNING" if alive else "FINISHED (awaiting cleanup)"
                wip = self.WIP_DIR / prompt
                wip_size = f"{wip.stat().st_size}b" if wip.exists() else "no WIP"
                lines.append(f"  {agent_name}: {prompt} (PID {pid}) [{state}] WIP: {wip_size}")
        else:
            lines.append("No queued agent running.")

        # Show ALL WIP files from main repo AND temp repos
        wip_files = sorted(self.WIP_DIR.glob("*.md")) if self.WIP_DIR.exists() else []
        temp_wips = self._find_temp_repo_wips()

        # Build combined list: prefer temp repo (more current while agent runs)
        all_wips = {}
        for wip in wip_files:
            all_wips[wip.name] = ("main", wip)
        for name, temp_path in temp_wips.items():
            all_wips[name] = ("LIVE", temp_path)

        if all_wips:
            lines.append(f"\nWIP files ({len(all_wips)}):")
            for name in sorted(all_wips.keys()):
                source, wip = all_wips[name]
                try:
                    size = wip.stat().st_size
                    content = wip.read_text(encoding='utf-8', errors='replace')
                    total_lines = len(content.splitlines())
                    last_line = ""
                    for l in reversed(content.splitlines()):
                        if l.strip():
                            last_line = l.strip()[:80]
                            break
                    tag = f" [{source}]" if source != "main" else ""
                    lines.append(f"  {name} ({size}b, {total_lines} lines){tag}")
                    if last_line:
                        lines.append(f"    last: {last_line}")
                except Exception:
                    lines.append(f"  {name} (unreadable)")

        if pending_tasks:
            lines.append(f"\nQueued ({len(pending_tasks)}):")
            for agent_name, prompt in pending_tasks[:10]:
                lines.append(f"  {agent_name}: {prompt}")
            if len(pending_tasks) > 10:
                lines.append(f"  ... and {len(pending_tasks) - 10} more")

        selected = self.get_data("selected_agent") or "sonnet"
        lines.append(f"\nSelected agent: {selected}")

        return "\n".join(lines)

    def _is_running_pid(self, pid):
        """Check if a specific PID is alive."""
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False

    def stop(self) -> str:
        """Stop the running agent."""
        pid = self.get_data( "current_pid" )
        if pid is None:
            return "No agent running."

        if not self._is_running():
            self._clear_state()
            return "Agent already finished. State cleared."

        try:
            if self.IS_WINDOWS:
                subprocess.run(["taskkill", "/F", "/PID", str(pid), "/T"], capture_output=True, timeout=10)
            else:
                os.kill( pid, signal.SIGTERM )
            # Give it 5 seconds
            for _ in range( 10 ):
                time.sleep( 0.5 )
                try:
                    if self.IS_WINDOWS:
                        result = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True)
                        if str(pid) not in result.stdout:
                            break
                    else:
                        os.kill( pid, 0 )
                except (OSError, ProcessLookupError):
                    break
            else:
                # Still alive, force kill
                if self.IS_WINDOWS:
                    subprocess.run(["taskkill", "/F", "/PID", str(pid), "/T"], capture_output=True, timeout=10)
                else:
                    os.kill( pid, signal.SIGKILL )
        except (OSError, ProcessLookupError):
            pass

        prompt = self.get_data( "current_prompt" )
        self._clear_state()
        return f"Agent stopped (was PID {pid}, prompt: {prompt})."

    def kill(self) -> str:
        """Kill the running agent and move WIP prompt back to ready."""
        pid = self.get_data( "current_pid" )
        prompt = self.get_data( "current_prompt" )

        if pid is None:
            return "No agent assigned."

        # Kill the process if still alive
        if self._is_running():
            try:
                os.kill( pid, signal.SIGKILL )
            except (OSError, ProcessLookupError):
                pass

        # Move wip back to ready
        if prompt:
            wip_path = self.WIP_DIR / prompt
            ready_path = self.READY_DIR / prompt
            if wip_path.exists():
                wip_path.rename( ready_path )
                self.log( f"Moved {prompt}: wip -> ready" )

        self._clear_state()
        return f"Agent killed (PID {pid}). Workorder '{prompt}' moved back to ready/."

    def tail(self, *args) -> str:
        """Tail the WIP journal file to see agent progress.

        Usage: agent tail [N] [filename]  (default 20 lines)

        If no filename given, shows ALL files in wip/ (main repo + temp repos).
        If filename given, shows just that file.
        While agent is running, checks the TEMP REPO wip (where agent writes).
        """
        n = 20
        target_file = None
        for arg in args:
            try:
                n = int(arg)
            except (ValueError, TypeError):
                target_file = str(arg)

        # If a specific file was requested
        if target_file:
            wip_path = self._find_wip_file(target_file)
            if not wip_path:
                return f"Workorder file not found: {target_file}"
            return self._tail_file(wip_path, n)

        # Collect WIP files from main repo
        wip_files = sorted(self.WIP_DIR.glob("*.md")) if self.WIP_DIR.exists() else []

        # Also check agent temp repos for live WIP files (agent writes there)
        temp_wip_files = self._find_temp_repo_wips()

        # Merge: prefer temp repo version over main repo version (more current)
        all_wips = {}
        for wip_path in wip_files:
            all_wips[wip_path.name] = ("main", wip_path)
        for name, temp_path in temp_wip_files.items():
            # Temp repo version is more current while agent is running
            all_wips[name] = ("temp", temp_path)

        if not all_wips:
            return "No WIP files found (checked main repo and agent temp repos)."

        if len(all_wips) == 1:
            source, path = list(all_wips.values())[0]
            return self._tail_file(path, n, source=source)

        # Multiple WIP files - show tail of each
        parts = [f"Found {len(all_wips)} WIP files:\n"]
        for name in sorted(all_wips.keys()):
            source, path = all_wips[name]
            parts.append(self._tail_file(path, n, source=source))
            parts.append("")
        return "\n".join(parts)

    def _find_temp_repo_wips(self):
        """Find WIP files in agent temp repos (where running agents write).

        Returns dict of {filename: Path} for WIP files found in temp repos.
        """
        result = {}
        import os
        import tempfile

        # Use Platform for temp repo path resolution
        plat = Platform()
        agent_work_base = plat.agent_work_base

        if not agent_work_base or not agent_work_base.exists():
            return result

        agents_dir = Platform.get_agents_dir()
        for agent_dir in agents_dir.iterdir():
            if not agent_dir.is_dir():
                continue
            # Check if agent has active work (pid file in queue/work/)
            work_dir = agent_dir / "queue" / "work"
            if not work_dir.exists():
                continue
            has_pid = any(work_dir.glob("*.pid"))
            if not has_pid:
                continue

            # Check temp repo for WIP files
            agent_name = agent_dir.name
            temp_repo = agent_work_base / agent_name / "repo"
            # Check standard locations
            for sub in ["workorders", "prompts"]:
                temp_wip_dir = temp_repo / sub / "wip"
                if temp_wip_dir.exists():
                    for f in temp_wip_dir.glob("*.md"):
                        result[f.name] = f
                    break
        return result

    def _find_wip_file(self, filename):
        """Find a workorder file in wip/, done/, or ready/. Returns Path or None."""
        for d in [self.WIP_DIR, self.DONE_DIR, self.READY_DIR]:
            p = d / filename
            if p.exists():
                return p
        return None

    def _tail_file(self, wip_path, n=20, source=None):
        """Return the last N lines of a file with a header."""
        try:
            with open(wip_path, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()
        except Exception as e:
            return f"ERROR reading {wip_path.name}: {e}"

        tail_lines = lines[-n:] if len(lines) > n else lines
        if source == "temp":
            header = "LIVE/temp-repo"
        elif wip_path.parent == self.WIP_DIR:
            header = "wip"
        elif wip_path.parent == self.DONE_DIR:
            header = "done"
        else:
            header = "ready"
        return f"[{header}/{wip_path.name}] (last {len(tail_lines)} of {len(lines)} lines):\n" + "".join(tail_lines)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_stale(self):
        """Check if the WIP file hasn't been updated recently. Returns warning or None."""
        prompt = self.get_data( "current_prompt" )
        if not prompt or not self._is_running():
            return None
        wip_path = self.WIP_DIR / prompt
        if not wip_path.exists():
            return None
        try:
            mtime = wip_path.stat().st_mtime
            age = time.time() - mtime
            if age > self.STALE_THRESHOLD_SECS:
                mins = int( age / 60 )
                return f"WARNING: WIP file unchanged for {mins}m — agent may be stuck"
        except OSError:
            pass
        return None

    def _clear_state(self):
        """Reset agent tracking state."""
        self.put_data( "current_pid", None, flush=False )
        self.put_data( "current_prompt", None, flush=False )
        self.put_data( "current_log", None, flush=False )
        self.put_data( "started_at", None )

    def _git_sync(self, msg):
        """Commit staged changes, push, pull."""
        try:
            subprocess.run(
                ["git", "add", "-A"],
                cwd=str( self.PROJECT_ROOT ),
                capture_output=True, timeout=30
            )
            subprocess.run(
                ["git", "commit", "-m", msg],
                cwd=str( self.PROJECT_ROOT ),
                capture_output=True, timeout=30
            )
            subprocess.run(
                ["git", "push"],
                cwd=str( self.PROJECT_ROOT ),
                capture_output=True, timeout=60
            )
            subprocess.run(
                ["git", "pull"],
                cwd=str( self.PROJECT_ROOT ),
                capture_output=True, timeout=60
            )
        except Exception as e:
            self.log( f"Git sync error: {e}" )

    def default(self, *args) -> str:
        """Show available commands."""
        selected = self.get_data( "selected_agent" ) or "haiku"
        label = self.KNOWN_AGENTS.get( selected, {} ).get( "label", selected )
        return (
            f"Agent Service (selected: {selected} — {label}):\n"
            "  list                   - List available AI backends\n"
            "  select <name>          - Select an agent backend\n"
            "  assign <prompt_file>   - Assign prompt and start agent\n"
            "  status                 - Show running agent info\n"
            "  stop                   - Stop running agent\n"
            "  kill                   - Kill agent, move WIP back to ready\n"
            "  tail [N]              - Tail WIP journal (default 20 lines)\n"
            "\n"
            "Agents: haiku, claude, opus, gemini-2.5-flash, gemini-2.5-flash-lite,\n"
            "        gemini-3-flash, gemini-3-pro, qwen, deepseek, codellama"
        )
