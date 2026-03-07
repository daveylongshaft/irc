import os
import sys
import json
import time
import shutil
import tarfile
import subprocess
from pathlib import Path
from datetime import datetime
from csc_service.server.service import Service
from csc_service.shared.services import PROJECT_ROOT as _PROJECT_ROOT


class benchmark(Service):
    """Benchmark service for running and tracking AI agent performance tests.

    Manages benchmark creation, execution, and results archival with timing data.
    Uses prompts_service to create benchmark prompts and agent_service to assign/run them.
    Results are stored as: <name>-<duration>-<agent>-<unixtime>.tgz
    This naming allows sorting by benchmark name, then speed, then agent, then time.

    Commands:
      add <name> <description>  - Add a new benchmark prompt
      del <name>                - Delete a benchmark
      run <name> <agent>        - Run a benchmark with specified agent
      list                      - List available benchmarks
      results <name>            - Show results for a benchmark
      results <name> <agent>    - Show results for a specific agent
    """

    PROJECT_ROOT = _PROJECT_ROOT
    BENCHMARKS_DIR = _PROJECT_ROOT / "benchmarks"
    PROMPTS_DIR = BENCHMARKS_DIR / "prompts"
    RESULTS_DIR = BENCHMARKS_DIR / "results"
    METADATA_FILE = BENCHMARKS_DIR / "benchmarks.json"

    def __init__(self, server_instance):
        super().__init__(server_instance)
        self.name = "benchmark"
        self.init_data()

        # Ensure directories exist
        self.PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
        self.RESULTS_DIR.mkdir(parents=True, exist_ok=True)

        # Load or initialize metadata
        if self.METADATA_FILE.exists():
            try:
                with open(self.METADATA_FILE, 'r', encoding='utf-8') as f:
                    self.benchmarks = json.load(f)
            except Exception as e:
                self.log(f"Error loading benchmarks metadata: {e}")
                self.benchmarks = {}
        else:
            self.benchmarks = {}

        self.log("Benchmark service initialized.")


    def _save_metadata(self):
        """Save benchmark metadata to disk."""
        try:
            with open(self.METADATA_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.benchmarks, f, indent=2)
        except Exception as e:
            self.log(f"Error saving benchmarks metadata: {e}")

    def _read_prompt_file(self, name):
        """Read a benchmark prompt file."""
        prompt_path = self.PROMPTS_DIR / f"{name}.md"
        if not prompt_path.exists():
            return None
        try:
            return prompt_path.read_text(encoding='utf-8')
        except Exception as e:
            self.log(f"Error reading prompt {name}: {e}")
            return None

    def _write_prompt_file(self, name, content):
        """Write a benchmark prompt file."""
        prompt_path = self.PROMPTS_DIR / f"{name}.md"
        try:
            prompt_path.write_text(content, encoding='utf-8')
            return True
        except Exception as e:
            self.log(f"Error writing prompt {name}: {e}")
            return False

    def add(self, name, *description_parts) -> str:
        """Add a new benchmark prompt.

        Usage: benchmark add <name> <description>
        """
        if not name:
            return "Error: Benchmark name required"

        name = name.strip().lower()
        if not name.replace('-', '').replace('_', '').isalnum():
            return f"Error: Invalid benchmark name '{name}'. Use alphanumeric, - or _"

        if name in self.benchmarks:
            return f"Error: Benchmark '{name}' already exists"

        # Treat remaining args as description
        description = ' '.join(description_parts) if description_parts else ""

        # Create a prompt template
        prompt_content = f"""# Benchmark: {name}

## Description
{description}

## Task
[Your task here - define what the agent should do]

## Acceptance
[Define when the task is complete]

## Work Log

"""

        if self._write_prompt_file(name, prompt_content):
            self.benchmarks[name] = {
                "created": int(time.time()),
                "description": description,
                "runs": []
            }
            self._save_metadata()
            self.log(f"Created benchmark: {name}")
            return f"Benchmark '{name}' created.\nEdit: tools/benchmarks/workorders/{name}.md\nRun: benchmark run {name} <agent>"
        else:
            return f"Error: Failed to create benchmark '{name}'"

    def delete(self, name) -> str:
        """Delete a benchmark prompt and its results.

        Usage: benchmark del <name>
        """
        if not name:
            return "Error: Benchmark name required"

        name = name.strip().lower()
        if name not in self.benchmarks:
            return f"Error: Benchmark '{name}' not found"

        # Delete prompt file
        prompt_path = self.PROMPTS_DIR / f"{name}.md"
        if prompt_path.exists():
            try:
                prompt_path.unlink()
            except Exception as e:
                return f"Error deleting prompt: {e}"

        # Delete result files
        deleted_count = 0
        for result_file in self.RESULTS_DIR.glob(f"{name}-*-*-*.tgz"):
            try:
                result_file.unlink()
                deleted_count += 1
            except Exception as e:
                self.log(f"Error deleting result {result_file}: {e}")

        # Delete from metadata
        del self.benchmarks[name]
        self._save_metadata()

        self.log(f"Deleted benchmark: {name} ({deleted_count} result files)")
        return f"Benchmark '{name}' deleted ({deleted_count} result files removed)"

    def run(self, name, agent_name) -> str:
        """Run a benchmark with the specified agent using the queue system.

        Usage: benchmark run <name> <agent>

        This method:
        1. Reads benchmark prompt template
        2. Creates WIP file in workorders/wip/ with combined prompt
        3. Puts prompt in agents/{agent_name}/queue/in/
        4. Monitors for COMPLETE tag in WIP file
        5. Archives results with timing data
        """
        if not name or not agent_name:
            return "Error: benchmark run <name> <agent>"

        name = name.strip().lower()
        agent_name = agent_name.strip().lower()

        if name not in self.benchmarks:
            return f"Error: Benchmark '{name}' not found"

        # Read benchmark prompt
        prompt_content = self._read_prompt_file(name)
        if not prompt_content:
            return f"Error: Could not read benchmark prompt '{name}'"

        try:
            # Create a unique filename for this benchmark run
            prompt_filename = f"benchmark-{name}-{int(time.time())}.md"

            # --- Step 1: Create WIP file with prompt (no README.1shot) ---
            # The wrapper will add README.1shot context when it runs.
            # DO NOT include README.1shot here - it contains the word "COMPLETE"
            # which would cause polling to exit immediately.
            wip_content = f"""# Benchmark: {name}
## Task
{prompt_content}

## Work Log

"""

            # Create WIP file
            wip_dir = self.PROJECT_ROOT / "workorders" / "wip"
            wip_dir.mkdir(parents=True, exist_ok=True)
            wip_file = wip_dir / prompt_filename

            try:
                wip_file.write_text(wip_content, encoding='utf-8')
                self.log(f"Created WIP file: {prompt_filename}")
            except Exception as e:
                return f"Error: Could not create WIP file: {e}"

            # --- Step 2: Put prompt in queue/in/ ---
            # Load agent info from agent_service
            from csc_service.shared.services.agent_service import agent as agent_service

            agent_svc = agent_service(None)  # Don't need server instance
            if agent_name not in agent_svc.KNOWN_AGENTS:
                return f"Error: Agent '{agent_name}' not found"

            # Create queue/in/ directory
            queue_in = self.PROJECT_ROOT / "agents" / agent_name / "queue" / "in"
            queue_in.mkdir(parents=True, exist_ok=True)

            # Create prompt file in queue/in/ (same content as WIP for reference)
            queue_prompt = queue_in / prompt_filename
            try:
                queue_prompt.write_text(wip_content, encoding='utf-8')
                self.log(f"Queued prompt for {agent_name}: {prompt_filename}")
            except Exception as e:
                return f"Error: Could not create queue prompt: {e}"

            # --- Step 3: Wait for completion ---
            start_time = time.time()
            self.log(f"Starting benchmark: {name} with agent: {agent_name}")

            completion_timeout = 3600  # 1 hour max
            poll_interval = 2  # Check every 2 seconds
            elapsed = 0

            while elapsed < completion_timeout:
                # Check if WIP file has COMPLETE tag
                try:
                    wip_text = wip_file.read_text(encoding='utf-8', errors='ignore')
                    if "COMPLETE" in wip_text:
                        end_time = time.time()
                        duration = end_time - start_time
                        self.log(f"Benchmark completed in {duration:.2f} seconds")

                        # Archive the result
                        success = self._archive_result(
                            name, agent_name, duration,
                            prompt_content, wip_text,
                            int(start_time)
                        )

                        if success:
                            # Clean up the WIP file
                            try:
                                wip_file.unlink()
                            except:
                                pass
                            # Clean up the queue prompt
                            try:
                                queue_prompt.unlink()
                            except:
                                pass
                            return f"Benchmark '{name}' completed in {duration:.2f}s\nResults archived"
                        else:
                            return f"Benchmark completed but failed to archive results"
                except Exception as e:
                    self.log(f"Error reading WIP file: {e}")

                time.sleep(poll_interval)
                elapsed += poll_interval

            # Timeout
            # Clean up on timeout
            try:
                wip_file.unlink()
            except:
                pass
            try:
                queue_prompt.unlink()
            except:
                pass

            return f"Error: Benchmark timed out after {completion_timeout}s"

        except Exception as e:
            self.log(f"Error running benchmark: {e}")
            import traceback
            traceback.print_exc()
            return f"Error: Failed to run benchmark: {e}"

    def _archive_result(self, name, agent_name, duration, prompt, result, start_time):
        """Archive benchmark result as a tarball with metadata."""
        try:
            unix_time = int(start_time)

            # Create a temporary directory for archive contents
            temp_dir = self.RESULTS_DIR / f"temp-{unix_time}"
            temp_dir.mkdir(exist_ok=True)

            try:
                # Write files to temp directory
                (temp_dir / "prompt.md").write_text(prompt, encoding='utf-8')
                (temp_dir / "result.md").write_text(result, encoding='utf-8')

                # Create metadata
                metadata = {
                    "benchmark": name,
                    "agent": agent_name,
                    "duration_seconds": duration,
                    "unix_timestamp": unix_time,
                    "datetime": datetime.fromtimestamp(unix_time).isoformat(),
                    "platform": sys.platform,
                    "python_version": sys.version
                }
                (temp_dir / "metadata.json").write_text(
                    json.dumps(metadata, indent=2),
                    encoding='utf-8'
                )

                # Create tarball with sorting-friendly name
                archive_name = f"{name}-{duration:.2f}-{agent_name}-{unix_time}.tgz"
                archive_path = self.RESULTS_DIR / archive_name

                with tarfile.open(str(archive_path), 'w:gz') as tar:
                    # Add files to archive
                    tar.add(str(temp_dir / "prompt.md"), arcname="prompt.md")
                    tar.add(str(temp_dir / "result.md"), arcname="result.md")
                    tar.add(str(temp_dir / "metadata.json"), arcname="metadata.json")

                self.log(f"Archived result: {archive_name}")

                # Update metadata
                if name in self.benchmarks:
                    self.benchmarks[name]["runs"].append({
                        "agent": agent_name,
                        "duration": duration,
                        "timestamp": unix_time,
                        "archive": archive_name
                    })
                    self._save_metadata()

                return True

            finally:
                # Clean up temp directory
                if temp_dir.exists():
                    shutil.rmtree(temp_dir)

        except Exception as e:
            self.log(f"Error archiving result: {e}")
            return False

    def list(self) -> str:
        """List all available benchmarks."""
        if not self.benchmarks:
            return "No benchmarks available. Create one: benchmark add <name> <description>"

        lines = ["Available Benchmarks:\n"]
        for name in sorted(self.benchmarks.keys()):
            meta = self.benchmarks[name]
            runs = len(meta.get("runs", []))
            created = datetime.fromtimestamp(meta["created"]).strftime("%Y-%m-%d %H:%M")
            desc = meta.get("description", "")[:60]
            lines.append(f"  {name:20} - {desc:60} ({runs} runs, created {created})")

        return "\n".join(lines)

    def results(self, name, agent_filter="") -> str:
        """Show results for a benchmark."""
        if not name:
            return "Usage: benchmark results <name> [agent]"

        name = name.strip().lower()
        agent_filter = agent_filter.strip().lower() if agent_filter else ""

        if name not in self.benchmarks:
            return f"Error: Benchmark '{name}' not found"

        meta = self.benchmarks[name]
        runs = meta.get("runs", [])

        if agent_filter:
            runs = [r for r in runs if r["agent"].lower() == agent_filter]
            if not runs:
                return f"No results for benchmark '{name}' with agent '{agent_filter}'"

        if not runs:
            return f"No results for benchmark '{name}'. Run: benchmark run {name} <agent>"

        # Sort by duration (fastest first)
        runs_sorted = sorted(runs, key=lambda r: r["duration"])

        lines = [f"Results for '{name}':\n"]
        for i, run in enumerate(runs_sorted, 1):
            timestamp = datetime.fromtimestamp(run["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")
            lines.append(
                f"  {i}. Agent: {run['agent']:20} | Duration: {run['duration']:7.2f}s | {timestamp}"
            )

        # Show archive files
        lines.append(f"\nArchive files in tools/benchmarks/results/:")
        for run in runs_sorted:
            lines.append(f"  {run['archive']}")

        return "\n".join(lines)

    def default(self, *args) -> str:
        """Show available commands."""
        return (
            "Benchmark Service:\n"
            "  add <name> <description>  - Create a benchmark\n"
            "  del <name>                - Delete a benchmark\n"
            "  run <name> <agent>        - Run benchmark with agent\n"
            "  list                      - List all benchmarks\n"
            "  results <name> [agent]    - Show results for benchmark\n"
        )
