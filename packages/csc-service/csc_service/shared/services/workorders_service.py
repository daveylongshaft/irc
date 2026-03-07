"""
Prompts Service - Work Queue Management

Allows AI clients to create, edit, and manage prompt files from IRC.
Prompts are stored in a queue system:
- ready/ - Tasks waiting to be executed
- wip/   - Tasks currently in progress
- done/  - Completed tasks
- hold/  - Tasks on hold

Service Commands (via IRC):
    AI <token> workorders add <description> : <content>
    AI <token> workorders list [ready|wip|done|all]
    AI <token> workorders read <filename>
    AI <token> workorders edit <filename> : <new_content>
    AI <token> workorders move <filename> <to_dir>
    AI <token> workorders delete <filename>
    AI <token> workorders status
"""

import os
import time
import subprocess
from pathlib import Path
from csc_service.server.service import Service
from csc_service.shared.utils import QueueDirectories
from csc_service.shared.services import PROJECT_ROOT
from csc_service.shared.services.agent_service import agent as AgentService


class workorders( Service ):
    """Service for managing prompt files in a work queue system."""

    PROJECT_ROOT = PROJECT_ROOT
    WORKORDERS_BASE = PROJECT_ROOT / "ops" / "wo"
    LEGACY_PROMPTS_BASE = PROJECT_ROOT / "ops" / "prompts"

    def __init__(self, server_instance):
        super().__init__( server_instance )
        self.name = "workorders"
        self.queue = QueueDirectories(self.WORKORDERS_BASE if self.WORKORDERS_BASE.exists() else self.LEGACY_PROMPTS_BASE)
        self._default_urgency = "P3"  # Default urgency level for new workorders
        self.log( "Workorders service initialized." )

    def urgency(self, *args) -> str:
        """Get or set default urgency level for new workorders.

        Usage:
            workorders urgency           # Returns current urgency (P0-P3)
            workorders urgency P0        # Sets default urgency to P0
            workorders urgency P3        # Sets default urgency to P3
        """
        if not args:
            return f"Current default urgency: {self._default_urgency}"

        level = args[0].strip().upper()
        if level not in ["P0", "P1", "P2", "P3"]:
            return "Error: Urgency must be P0, P1, P2, or P3"

        self._default_urgency = level
        return f"Default urgency set to: {level}"

    def _sanitize_filename(self, description):
        """Convert description to safe filename component."""
        safe = "".join(c if c.isalnum() or c in ("-", "_") else "_"
                      for c in description.lower())
        safe = "_".join(filter(None, safe.split("_")))
        return safe[:50]


    # Agents are managed by the agent service — prompts assign delegates there

    def _format_prompt_list(self, dir_name, files):
        """Format a numbered list of workorders with urgency and tags."""
        if not files:
            return f"[workorders/{dir_name}] No workorders found"

        lines = [f"[workorders/{dir_name}] {len(files)} workorder(s):"]
        for i, filename in enumerate(files, 1):
            # Check for front-matter tags
            filepath = self.queue.get(dir_name) / filename
            tags = AgentService._parse_front_matter(filepath)
            tag_str = ""
            urgency_str = ""

            if tags:
                parts = []

                # Show urgency prominently (P0/P1 are urgent, P3 is low-cost)
                if "urgency" in tags:
                    urgency = tags["urgency"]
                    urgency_str = f" {urgency}"
                    if urgency in ["P0", "P1"]:
                        urgency_str += "(URGENT)"
                    elif urgency == "P3":
                        urgency_str += "(cost-opt)"

                # Show other metadata
                if "requires" in tags:
                    req = tags["requires"]
                    if isinstance(req, list):
                        parts.append(f"req:{','.join(req)}")
                    else:
                        parts.append(f"req:{req}")
                if "platform" in tags:
                    plat = tags["platform"]
                    if isinstance(plat, list):
                        parts.append(f"plat:{','.join(plat)}")
                    else:
                        parts.append(f"plat:{plat}")
                if "min_ram" in tags:
                    parts.append(f"ram:{tags['min_ram']}")
                if "cost_sensitive" in tags and tags["cost_sensitive"]:
                    parts.append("cost-sensitive")

                if parts:
                    tag_str = f" [{' '.join(parts)}]"

            lines.append(f"  {i}. {filename}{urgency_str}{tag_str}")

        return "\n".join(lines)

    def add(self, *args) -> str:
        """Create a new workorder with metadata and execution mode support.

        Usage:
            workorders add <description> : <content>
            workorders add <description> urgency=P0 requires=docker : <content>
            workorders add <description> P1 : <content>  # shorthand urgency

        Supported metadata:
            urgency=P0|P1|P2|P3  - Priority (default from workorders urgency setting)
            requires=x,y         - Required tools/capabilities
            platform=linux,macos - Required OS
            min_ram=2GB          - Required memory
            cost_sensitive=true  - Force queue mode for cost optimization

        Examples:
            AI 1 workorders add Fix critical bug P0 : Fix auth.py vulnerability
            AI 1 workorders add New feature : Implement feature X with...
            AI 1 workorders add Batch job urgency=P3 cost_sensitive=true : Refactor...
        """
        import re

        args_string = " ".join( args )
        if " : " not in args_string:
            return (
                "Usage: workorders add <description> [urgency=P0-P3 requires=x,y platform=z] : <content>\n"
                "Or: workorders add <description> [P0|P1|P2|P3] : <content>"
            )

        parts = args_string.split(" : ", 1)
        desc_and_tags = parts[0].strip()
        content = parts[1].strip()

        if not desc_and_tags or not content:
            return "Error: Both description and content required"

        # Parse optional tags and shorthand urgency from description line
        # Format: "description urgency=P0 requires=docker,git platform=linux"
        #      or: "description P0 requires=docker"
        tag_pattern = r'\b(urgency|requires|platform|min_ram|cost_sensitive)=(\S+)'
        found_tags = re.findall(tag_pattern, desc_and_tags)
        description = re.sub(tag_pattern, '', desc_and_tags).strip()

        # Check for shorthand urgency (P0-P3) and add as tag
        urgency_shorthand = re.search(r'\b(P[0-3])\b', description)
        if urgency_shorthand:
            urgency_value = urgency_shorthand.group(1)
            description = re.sub(r'\bP[0-3]\b', '', description).strip()
            # Add to found_tags if not already specified with urgency=
            if not any(tag[0] == 'urgency' for tag in found_tags):
                found_tags.append(('urgency', urgency_value))

        if not description:
            return "Error: Description required"

        # Build front-matter with all tags plus default urgency
        fm_lines = ["---"]

        # Always include urgency (from tag, default, or setting)
        urgency_value = None
        for key, value in found_tags:
            if key == 'urgency':
                urgency_value = value
                break

        if not urgency_value:
            urgency_value = self._default_urgency

        # Validate urgency
        if urgency_value not in ["P0", "P1", "P2", "P3"]:
            return f"Error: Invalid urgency '{urgency_value}'. Must be P0, P1, P2, or P3"

        fm_lines.append(f"urgency: {urgency_value}")

        # Add other tags
        for key, value in found_tags:
            if key != 'urgency':  # Already added above
                if "," in value:
                    items = ", ".join(value.split(","))
                    fm_lines.append(f"{key}: [{items}]")
                else:
                    fm_lines.append(f"{key}: {value}")

        fm_lines.append("---")
        front_matter = "\n".join(fm_lines) + "\n"

        timestamp = int(time.time())
        safe_desc = self._sanitize_filename(description)
        filename = f"{timestamp}-{safe_desc}.md"
        filepath = self.queue.get("ready") / filename

        try:
            full_content = front_matter + content.strip() + "\n"
            filepath.write_text(full_content, encoding="utf-8")

            # Build info string showing metadata
            info_parts = [f"urgency={urgency_value}"]
            for key, value in found_tags:
                if key != 'urgency':
                    info_parts.append(f"{key}={value}")
            tag_info = f" ({', '.join(info_parts)})" if info_parts else ""

            return f"Created workorder: {filename} in ready/{tag_info}"
        except Exception as e:
            return f"Error creating workorder: {e}"

    def list(self, *args) -> str:
        """List workorders in specified directory or all directories.

        Usage: workorders list [ready|wip|done|hold|all]
        """
        target = args[0].strip().lower() if args else "all"

        if target in self.queue.ALL_DIRS:
            files = self.queue.list_files(target)
            return self._format_prompt_list(target, files)

        elif target == "all" or not target:
            results = []
            for dir_name in ["ready", "wip", "hold", "done"]:
                files = self.queue.list_files(dir_name)
                results.append(self._format_prompt_list(dir_name, files))
            return "\n".join(results)

        else:
            return "Usage: workorders list [ready|wip|done|hold|all]"

    def read(self, filename: str) -> str:
        """Read and display a prompt file.

        Usage: workorders read <filename>
        """
        if not filename:
            return "Usage: workorders read <filename>"

        filepath, dir_name = self.queue.find_file(filename.strip())

        if not filepath:
            return f"File not found: {filename}"

        try:
            content = filepath.read_text(encoding="utf-8")
            max_lines = 20
            lines = content.split("\n")
            if len(lines) > max_lines:
                content = "\n".join(lines[:max_lines])
                content += f"\n... ({len(lines) - max_lines} more lines)"

            return f"[{dir_name}] {filepath.name}:\n{content}"
        except Exception as e:
            return f"Error reading file: {e}"

    def edit(self, *args) -> str:
        """Edit an existing prompt file.

        Usage: workorders edit <filename> : <new_content>
        """
        args_string = " ".join( args )
        if " : " not in args_string:
            return "Usage: workorders edit <filename> : <new_content>"

        parts = args_string.split(" : ", 1)
        filename = parts[0].strip()
        content = parts[1].strip()

        if not filename or not content:
            return "Error: Both filename and content required"

        filepath, dir_name = self.queue.find_file(filename)

        if not filepath:
            return f"File not found: {filename}"

        try:
            filepath.write_text(content.strip() + "\n", encoding="utf-8")
            return f"Updated: {filepath.name} in {dir_name}/"
        except Exception as e:
            return f"Error editing file: {e}"

    def append(self, *args) -> str:
        """Append content to an existing prompt file.

        Usage: workorders append <filename> : <content>
        
        Appends content to the end of a file. Useful for adding notes or logs
        after a workorder is processed. Optionally adds a timestamp prefix.
        """
        args_string = " ".join(args)
        if " : " not in args_string:
            return "Usage: workorders append <filename> : <content>"

        parts = args_string.split(" : ", 1)
        filename = parts[0].strip()
        content = parts[1].strip()

        if not filename or not content:
            return "Error: Both filename and content required"

        filepath, dir_name = self.queue.find_file(filename)

        if not filepath:
            return f"File not found: {filename}"

        try:
            # Read existing content
            existing = filepath.read_text(encoding="utf-8")
            
            # Append new content with timestamp
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            appended = f"{existing}\n[{timestamp}] {content}\n"
            
            filepath.write_text(appended, encoding="utf-8")
            return f"Appended to: {filepath.name} in {dir_name}/"
        except Exception as e:
            return f"Error appending to file: {e}"

    def _resolve_prompt(self, ref, from_dir="ready"):
        """Resolve a prompt reference (number or filename) to a filepath.
        Numbers are 1-indexed into the sorted file list of from_dir.
        Returns (filepath, dir_name) or (None, None).
        """
        try:
            index = int(ref) - 1
            files = self.queue.list_files(from_dir)
            if 0 <= index < len(files):
                return self.queue.get(from_dir) / files[index], from_dir
            return None, None
        except (ValueError, TypeError):
            return self.queue.find_file(ref)

    def assign(self, *args) -> str:
        """Assign a workorder to an agent with execution mode support.

        Supports both Anthropic models (haiku, sonnet, opus) with direct API mode
        for P0/P1 tasks, and other providers (gemini, chatgpt, ollama, etc.) via
        queue-worker (traditional mode).

        Usage:
            workorders assign <number|filename> <agent>
            workorders assign 1 haiku            # P0/P1 may use direct API
            workorders assign 1 gemini-3-pro     # Always uses queue-worker
            workorders assign 1 opus             # P0/P1 may use direct API

        Agents:
            Anthropic: haiku, sonnet, opus (support both direct API and queue)
            Google:    gemini-2.5-flash, gemini-3-flash, gemini-3-pro (queue only)
            OpenAI:    chatgpt (queue only)
            Local:     ollama-*, codellama (queue only)
        """
        args_string = " ".join(args).strip()
        parts = args_string.split()
        if len(parts) < 2:
            return (
                "Usage: workorders assign <number|filename> <agent>\n"
                "Anthropic: haiku, sonnet, opus\n"
                "Google: gemini-2.5-flash, gemini-3-flash, gemini-3-pro\n"
                "OpenAI: chatgpt\n"
                "Local: ollama-*, codellama"
            )

        ref = parts[0]
        agent_name = parts[1].lower()

        # Resolve numbered reference to filename
        filepath, from_dir = self._resolve_prompt(ref)
        if not filepath:
            return f"Workorder not found: {ref}"

        # Check if this is an Anthropic model that supports direct API execution
        is_anthropic_model = agent_name in ["haiku", "sonnet", "opus"]
        supports_direct_api = is_anthropic_model

        # Try to use PM executor for Anthropic models (intelligent routing)
        if supports_direct_api:
            try:
                from csc_service.infra.pm_executor import PMExecutor
                from pathlib import Path
                import json

                # Read workorder to extract metadata
                wo_content = filepath.read_text(encoding="utf-8")
                urgency = "P2"  # Default

                # Extract urgency from front matter
                if wo_content.startswith("---"):
                    lines = wo_content.split("\n")
                    for line in lines[1:]:
                        if line.strip() == "---":
                            break
                        if line.startswith("urgency:"):
                            urgency = line.split(":", 1)[1].strip().upper()

                # Build task config for mode selection
                task_config = {
                    "task_name": filepath.name,
                    "urgency": urgency,
                    "agent": agent_name,
                    "content": wo_content,
                    "cost_sensitive": "cost_sensitive: true" in wo_content.lower(),
                }

                # Get executor and select mode
                executor = PMExecutor(self.PROJECT_ROOT)
                execution_mode, selected_agent = executor.select_execution_mode(task_config)

                if execution_mode == "direct":
                    # Execute directly for P0/P1 urgent tasks
                    self.log(f"Direct API execution: {filepath.name} ({urgency}) via {selected_agent}")
                    result = executor.execute_task_direct_api(task_config, selected_agent)

                    # Move to done if successful
                    if result.get("success"):
                        done_dir = self.WORKORDERS_BASE / "done"
                        done_dir.mkdir(parents=True, exist_ok=True)
                        filepath.rename(done_dir / filepath.name)
                        return (
                            f"[Direct API] Completed: {filepath.name}\n"
                            f"Agent: {selected_agent} | Duration: {result.get('duration')}s | "
                            f"Turns: {result.get('turns')}\n"
                            f"Result: {result.get('output', '')[:200]}"
                        )
                    else:
                        return f"[Direct API] Failed: {filepath.name}\nError: {result.get('error', 'Unknown error')}"

                # Fall through to queue-worker for P2/P3 or if direct fails

            except Exception as e:
                self.log(f"Warning: PM executor unavailable, using queue-worker: {e}")
                # Fall through to queue-worker

        # Use traditional queue-worker flow (works for all agents)
        try:
            # Directly import and instantiate agent service
            import importlib
            agent_module = importlib.import_module("csc_shared.services.agent_service")
            agent_class = getattr(agent_module, "agent", None)
            if not agent_class:
                return "Error: agent service class not found"

            agent_svc = agent_class(self.server)

            # Check if agent is available
            select_result = agent_svc.select(agent_name)
            if "Unknown" in select_result or "not installed" in select_result:
                return select_result

            # Assign to queue-worker (traditional flow)
            assign_result = agent_svc.assign(filepath.name)
            return assign_result

        except Exception as e:
            return f"Error delegating to agent service: {e}"

    def move(self, *args) -> str:
        """Move a prompt between directories.

        Usage: workorders move <number|filename> <to_dir>
        """
        if len(args) < 2:
            return "Usage: workorders move <number|filename> <to_dir>"

        filename = args[0]
        to_dir = args[1].lower()

        if to_dir not in self.queue.ALL_DIRS:
            return "Invalid directory. Use: ready, wip, hold, or done"

        filepath, from_dir = self._resolve_prompt(filename)

        if not filepath:
            return f"File not found: {filename}"

        if from_dir == to_dir:
            return f"File already in {to_dir}/"

        try:
            success = self.queue.move_file(filepath.name, from_dir, to_dir)
            if success:
                return f"Moved {filepath.name}: {from_dir} -> {to_dir}"
            else:
                return f"Error moving file"
        except Exception as e:
            return f"Error moving file: {e}"

    def delete(self, filename: str) -> str:
        """Delete a prompt file.

        Usage: workorders delete <filename>
        """
        if not filename:
            return "Usage: workorders delete <filename>"

        filepath, dir_name = self.queue.find_file(filename.strip())

        if not filepath:
            return f"File not found: {filename}"

        try:
            if hasattr(self.server, 'create_new_version'):
                self.server.create_new_version(str(filepath))
            filepath.unlink()
            return f"Deleted: {filepath.name} from {dir_name}/"
        except Exception as e:
            return f"Error deleting file: {e}"

    def status(self) -> str:
        """Show status of all prompt directories."""
        counts = self.queue.get_counts()
        total = sum(counts.values())

        return (
            f"Prompts status:\n"
            f"  Ready: {counts['ready']} | WIP: {counts['wip']} | Hold: {counts['hold']} | Done: {counts['done']}\n"
            f"  Total: {total}"
        )

    def archive(self, filename: str) -> str:
        """Archive a completed prompt from done/ to archive/.
        Requires the prompt to end with 'verified complete' or 'dead end'.

        Usage: workorders archive <filename>
        """
        if not filename:
            return "Usage: workorders archive <filename>"

        filepath, dir_name = self.queue.find_file(filename.strip())

        if not filepath or dir_name != self.queue.DONE:
            return f"File not found in done/: {filename}"

        # Read the last line to check for completion status
        content_lines = filepath.read_text(encoding="utf-8").strip().splitlines()
        if not content_lines:
            return f"Error: {filename} is empty. Cannot archive."

        last_line = content_lines[-1].lower()
        if "verified complete" not in last_line and "dead end" not in last_line:
            return f"Error: {filename} must end with 'verified complete' or 'dead end' to be archived."

        try:
            success = self.queue.move_file(filepath.name, self.queue.DONE, self.queue.ARCHIVE)
            if success:
                return f"Archived {filepath.name}: {self.queue.DONE} -> {self.queue.ARCHIVE}"
            else:
                return f"Error archiving file"
        except Exception as e:
            return f"Error archiving file: {e}"

    def default(self, *args) -> str:
        """Show available commands."""
        return (
            "Workorders Service - Work Queue:\n"
            "  add <desc> : <content>      - Create a new prompt in ready/\n"
            "  list [ready|wip|done|all]    - List numbered prompts\n"
            "  read <#|filename>           - Read a prompt file\n"
            "  edit <filename> : <content> - Edit a prompt file\n"
            "  append <filename> : <text>  - Append text to a prompt file\n"
            "  move <#|filename> <dir>     - Move between ready/wip/done/hold/archive\n"
            "  archive <filename>          - Archive a verified complete/dead end prompt from done/\n"
            "  assign <#|filename> <agent> - Move to wip and launch agent\n"
            "  delete <filename>           - Delete a prompt file\n"
            "  status                      - Show queue counts"
        )


class prompts(workorders):
    """Compatibility alias for legacy prompts service."""

