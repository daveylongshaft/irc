#!/usr/bin/env python3
"""
Batch API Tool Loop Executor

Implements the full batch tool execution loop:
1. Retrieves batch results from Anthropic API
2. Parses tool_use blocks (run_command, read_file, write_file, list_directory)
3. Executes tools locally in CSC project root
4. Creates tool_result blocks with tool_use_id
5. Submits follow-up batches with results
6. Loops until stop_reason = "end_turn"

Usage:
    python batch_executor.py <batch_id1> [batch_id2] ...
    python batch_executor.py --all-restructure-phases
"""

import os
import sys
import json
import time
import subprocess
import argparse
from pathlib import Path
from datetime import datetime
from typing import Any, Optional

# Fix Windows console encoding issue
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# CSC paths - try to use Platform object for intelligent resolution
try:
    from csc_service.shared.platform import Platform
    _platform = Platform()
    CSC_ROOT = Path(_platform.get_abs_root_path([]))
except Exception:
    CSC_ROOT = Path(__file__).resolve().parents[2]

# Add CSC packages to path for Service access
sys.path.insert(0, str(CSC_ROOT / "irc" / "packages" / "csc-service"))
sys.path.insert(0, str(CSC_ROOT / "irc" / "packages" / "csc-shared"))

# Import CSC service layer for consistent logging
try:
    # Import just the logging utilities, don't instantiate full Service
    from csc_service.shared.logging import CSCLogger
    HAS_SERVICE = True
except ImportError:
    try:
        # Fallback: import what we can
        CSCLogger = None
        HAS_SERVICE = False
    except:
        CSCLogger = None
        HAS_SERVICE = False

# Model escalation chain: start with cheapest, escalate to more capable
ESCALATION_CHAIN = [
    "claude-haiku-4-5-20251001",
    "claude-sonnet-4-20250514",
    "claude-opus-4-20250514"
]

# Default retry settings
DEFAULT_MAX_RETRIES = 2
LOGS_DIR = CSC_ROOT / "logs"
LOGS_DIR.mkdir(exist_ok=True)

# Tool definitions for follow-up batches
TOOLS = [
    {
        "name": "read_file",
        "description": "Read the contents of a file",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path to file"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "write_file",
        "description": "Write content to a file (creates or overwrites)",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path to file"},
                "content": {"type": "string", "description": "File content to write"}
            },
            "required": ["path", "content"]
        }
    },
    {
        "name": "list_directory",
        "description": "List files and subdirectories in a directory",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "run_command",
        "description": "Execute a bash command and capture output",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Bash command to execute"}
            },
            "required": ["command"]
        }
    }
]


def get_api_key() -> str:
    """Extract API key from .env file or environment."""
    # Try .env file first
    env_file = CSC_ROOT / ".env"
    if env_file.exists():
        content = env_file.read_text()
        for line in content.split("\n"):
            if "ANTHROPIC_API_KEY_3=" in line and "sk-" in line:
                return line.split('"')[1]

    # Fall back to environment
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key

    raise RuntimeError("ANTHROPIC_API_KEY not found in .env or environment")


def log(msg: str, level: str = "INFO"):
    """Log message with timestamp."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    prefix = {"INFO": " ", "OK": "+", "ERR": "!", "TOOL": ">", "WAIT": "~", "RETRY": "R", "ESC": "^"}
    print(f"[{timestamp}] [{prefix.get(level, ' ')}] {msg}", flush=True)


def get_model_short_name(model: str) -> str:
    """Get short display name for model."""
    if "haiku" in model.lower():
        return "haiku"
    elif "sonnet" in model.lower():
        return "sonnet"
    elif "opus" in model.lower():
        return "opus"
    return model[:20]


class BatchToolExecutor:
    """Execute batch tool loops until completion with retry and escalation support."""

    def __init__(self, api_key: str, max_retries: int = DEFAULT_MAX_RETRIES):
        import anthropic
        self.client = anthropic.Anthropic(api_key=api_key)
        self.execution_log: list[dict] = []
        self.total_tools_executed = 0
        self.total_batches_submitted = 0
        self.max_retries = max_retries

        # Per-phase tracking
        self.phase_results: list[dict] = []
        self.current_model_index = 0  # Index into ESCALATION_CHAIN
        self.retry_count = 0
        self.tool_errors: list[dict] = []  # Track tool execution errors

        # CSC logging integration (no need to instantiate full Service)
        self.has_csc_logger = HAS_SERVICE and CSCLogger is not None
        self.verbose_log(f"[INIT] BatchToolExecutor ready - max_retries={max_retries}, csc_logger={self.has_csc_logger}")

    def verbose_log(self, msg: str, level: str = "INFO"):
        """Log with CSC logging if available, store in execution log."""
        log(msg, level)
        # Always store in execution log for analysis
        self.execution_log.append({
            "timestamp": datetime.now().isoformat(),
            "type": "executor_log",
            "message": msg,
            "level": level
        })

    def get_current_model(self) -> str:
        """Get the current model from escalation chain."""
        return ESCALATION_CHAIN[min(self.current_model_index, len(ESCALATION_CHAIN) - 1)]

    def reset_for_phase(self):
        """Reset retry/escalation state for a new phase."""
        self.current_model_index = 0
        self.retry_count = 0
        self.tool_errors = []

    def should_escalate(self) -> bool:
        """Check if we should escalate to next model."""
        return (self.retry_count >= self.max_retries and
                self.current_model_index < len(ESCALATION_CHAIN) - 1)

    def escalate_model(self) -> str:
        """Escalate to next model in chain. Returns new model name."""
        old_model = get_model_short_name(self.get_current_model())
        self.current_model_index += 1
        self.retry_count = 0  # Reset retries for new model
        new_model = get_model_short_name(self.get_current_model())
        log(f"Escalating: {old_model} -> {new_model}", "ESC")
        return self.get_current_model()

    def _normalize_path(self, path: str) -> str:
        """Convert Cygwin paths (/c/...) to Windows paths (C:\...) for Python file ops."""
        if path.startswith("/c/"):
            try:
                result = subprocess.run(["cygpath", "-w", path], capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    converted = result.stdout.strip()
                    self.verbose_log(f"[PATH] Converted {path} -> {converted}", "PATH")
                    # CRITICAL: Verify the converted path exists
                    import os
                    if os.path.exists(converted):
                        self.verbose_log(f"[PATH] Verified: converted path EXISTS", "PATH")
                        return converted
                    else:
                        self.verbose_log(f"[PATH] WARNING: converted path does not exist: {converted}", "WARN")
                        return converted
                else:
                    self.verbose_log(f"[PATH] cygpath FAILED (rc={result.returncode}): {result.stderr.strip()}", "WARN")
                    return path
            except Exception as e:
                self.verbose_log(f"[PATH] cygpath EXCEPTION: {str(e)}", "WARN")
                return path
        return path

    def _try_alternative_paths(self, path: str) -> list:
        """Generate alternative paths to try if primary path fails."""
        alternatives = [path]

        # If it has workorders/ready, try ops/wo/ready
        if "workorders/ready" in path:
            alt = path.replace("workorders/ready", "ops/wo/ready")
            if alt != path:
                alternatives.append(alt)

        return alternatives

    def execute_tool(self, name: str, input_data: dict) -> tuple[str, bool, float]:
        """
        Execute a tool and return (result_text, is_error, execution_time_ms).
        """
        start_time = time.time()
        try:
            if name == "run_command":
                cmd = input_data.get("command", "")
                self.verbose_log(f"[TOOL_EXEC] run_command START: {cmd[:100]}", "TOOL")
                result = subprocess.run(
                    cmd, shell=True, capture_output=True, text=True,
                    timeout=120, cwd=str(CSC_ROOT)
                )
                output = result.stdout + result.stderr
                elapsed_ms = (time.time() - start_time) * 1000
                returnval = result.returncode
                self.verbose_log(f"[TOOL_EXEC] run_command DONE: returncode={returnval}, output_len={len(output)}, time={elapsed_ms:.0f}ms", "TOOL")
                if output.strip():
                    self.verbose_log(f"[TOOL_EXEC] run_command OUTPUT:\n{output[:500]}", "TOOL")
                return (output if output.strip() else "(success, no output)"), False, elapsed_ms

            elif name == "read_file":
                path = input_data.get("path", "")
                self.verbose_log(f"[TOOL_EXEC] read_file START: {path}", "TOOL")

                # Generate all paths to try: alternatives + multiple formats
                alt_paths = self._try_alternative_paths(path)

                # For each alternative, also try Windows path conversion
                all_try_paths = []
                for alt_path in alt_paths:
                    all_try_paths.append(alt_path)
                    # Also try normalized Windows version
                    if alt_path.startswith("/c/"):
                        win_version = alt_path.replace("/c/", "C:\\").replace("/", "\\")
                        all_try_paths.append(win_version)

                self.verbose_log(f"[TOOL_EXEC] read_file trying {len(all_try_paths)} path variant(s)", "TOOL")
                content = None
                last_error = None

                for i, try_path in enumerate(all_try_paths):
                    try:
                        norm_path = self._normalize_path(try_path)
                        self.verbose_log(f"[TOOL_EXEC] read_file [{i}] trying: {try_path} -> {norm_path}", "TOOL")
                        with open(norm_path, 'r', encoding='utf-8', errors='replace') as f:
                            content = f.read()
                        self.verbose_log(f"[TOOL_EXEC] read_file SUCCESS via variant [{i}]: {norm_path} ({len(content)} bytes)", "TOOL")
                        break
                    except FileNotFoundError as e:
                        last_error = f"FileNotFound at variant {i}: {try_path}"
                        continue
                    except Exception as e:
                        last_error = f"Exception at variant {i}: {str(e)}"
                        continue

                if content is None:
                    elapsed_ms = (time.time() - start_time) * 1000
                    error_msg = f"ERROR: {last_error or 'File not readable'}"
                    self.verbose_log(f"[TOOL_EXEC] read_file FINAL FAILURE: {error_msg}", "ERR")
                    self.tool_errors.append({"tool": "read_file", "error": error_msg, "input": input_data})
                    return error_msg, True, elapsed_ms

                # Truncate large files
                if len(content) > 8000:
                    content = content[:8000] + f"\n\n... (truncated, {len(content)} total chars)"
                elapsed_ms = (time.time() - start_time) * 1000
                self.verbose_log(f"[TOOL_EXEC] read_file DONE: content_len={len(content)}, time={elapsed_ms:.0f}ms", "TOOL")
                return content, False, elapsed_ms

            elif name == "write_file":
                path = input_data.get("path", "")
                content = input_data.get("content", "")
                self.verbose_log(f"[TOOL_EXEC] write_file START: {path} ({len(content)} bytes)", "TOOL")
                # Normalize Cygwin paths
                norm_path = self._normalize_path(path)
                try:
                    os.makedirs(os.path.dirname(norm_path), exist_ok=True)
                    with open(norm_path, 'w', encoding='utf-8') as f:
                        f.write(content)
                except Exception as e:
                    elapsed_ms = (time.time() - start_time) * 1000
                    error_msg = f"ERROR: {str(e)}"
                    return error_msg, True, elapsed_ms
                elapsed_ms = (time.time() - start_time) * 1000
                self.verbose_log(f"[TOOL_EXEC] write_file DONE: {path}, time={elapsed_ms:.0f}ms", "TOOL")
                return f"Written: {path} ({len(content)} chars)", False, elapsed_ms

            elif name == "list_directory":
                path = input_data.get("path", "")
                self.verbose_log(f"[TOOL_EXEC] list_directory START: {path}", "TOOL")
                # Normalize Cygwin paths
                norm_path = self._normalize_path(path)
                if not os.path.exists(norm_path):
                    elapsed_ms = (time.time() - start_time) * 1000
                    error_msg = f"ERROR: Directory not found: {path}"
                    self.verbose_log(f"[TOOL_EXEC] list_directory ERROR: path does not exist", "ERR")
                    self.tool_errors.append({"tool": name, "error": error_msg, "input": input_data})
                    return error_msg, True, elapsed_ms
                items = sorted(os.listdir(norm_path))
                elapsed_ms = (time.time() - start_time) * 1000
                self.verbose_log(f"[TOOL_EXEC] list_directory DONE: {len(items)} items, time={elapsed_ms:.0f}ms", "TOOL")
                return "\n".join(items), False, elapsed_ms

            else:
                elapsed_ms = (time.time() - start_time) * 1000
                error_msg = f"Unknown tool: {name}"
                self.tool_errors.append({"tool": name, "error": error_msg, "input": input_data})
                return error_msg, True, elapsed_ms

        except subprocess.TimeoutExpired:
            elapsed_ms = (time.time() - start_time) * 1000
            error_msg = "ERROR: Command timed out after 120s"
            self.tool_errors.append({"tool": name, "error": error_msg, "input": input_data})
            return error_msg, True, elapsed_ms
        except Exception as e:
            elapsed_ms = (time.time() - start_time) * 1000
            error_msg = f"ERROR: {str(e)}"
            self.tool_errors.append({"tool": name, "error": error_msg, "input": input_data})
            return error_msg, True, elapsed_ms

    def wait_for_batch(self, batch_id: str, max_wait: int = 3600) -> dict:
        """
        Poll batch status with exponential backoff until complete or timeout.
        Strategy: 2s initial, 5s next, then 1.5x backoff capped at 2min between checks.
        """
        start_time = time.time()
        last_status = None
        wait_times = [2, 5]  # Initial waits: 2s, then 5s
        current_wait_idx = 0

        while True:
            elapsed = time.time() - start_time
            if elapsed > max_wait:
                raise TimeoutError(f"Batch {batch_id} did not complete within {max_wait}s")

            batch = self.client.beta.messages.batches.retrieve(batch_id)
            status = batch.processing_status

            if status != last_status:
                log(f"Batch {batch_id[:20]}... status: {status}", "WAIT")
                last_status = status

            if status == "ended":
                return batch

            # Get next wait time
            if current_wait_idx < len(wait_times):
                next_wait = wait_times[current_wait_idx]
                current_wait_idx += 1
            else:
                # Exponential backoff: 1.5x previous, capped at 120s (2 min)
                next_wait = min(int(wait_times[-1] * 1.5), 120)
                wait_times.append(next_wait)

            time.sleep(next_wait)

    def process_batch(self, batch_id: str, phase_name: str = "") -> dict:
        """
        Process a single batch: retrieve results, execute tools, return state.

        Returns dict with:
            - stop_reason: "end_turn" | "tool_use" | "max_tokens" | error
            - tool_results: list of tool result dicts (if stop_reason == "tool_use")
            - assistant_content: list of content blocks from assistant
            - text_output: combined text from assistant
        """
        log(f"Processing batch: {batch_id}", "INFO")
        if phase_name:
            log(f"Phase: {phase_name}", "INFO")

        # Wait for batch to complete
        batch = self.wait_for_batch(batch_id)

        # Retrieve results
        results = list(self.client.beta.messages.batches.results(batch_id))

        if not results:
            return {"stop_reason": "error", "error": "No results in batch"}

        # Process each result (typically just one for our use case)
        all_tool_results = []
        all_assistant_content = []
        text_output = []
        final_stop_reason = "end_turn"
        custom_id = None
        model = None

        for result in results:
            custom_id = result.custom_id

            if result.result.type != "succeeded":
                log(f"Result {custom_id} failed: {result.result.type}", "ERR")
                continue

            message = result.result.message
            model = message.model
            stop_reason = message.stop_reason
            final_stop_reason = stop_reason

            log(f"Result {custom_id}: stop_reason={stop_reason}", "OK")

            # Process content blocks
            for block in message.content:
                all_assistant_content.append(block)

                if block.type == "text":
                    text_output.append(block.text)
                    # Print text (truncated for readability)
                    preview = block.text[:500].replace("\n", " ")
                    if len(block.text) > 500:
                        preview += "..."
                    log(f"Text: {preview}", "INFO")

                elif block.type == "tool_use":
                    self.total_tools_executed += 1
                    tool_id = block.id
                    tool_name = block.name
                    tool_input = block.input

                    # Execute the tool (with timing)
                    output, is_error, exec_time_ms = self.execute_tool(tool_name, tool_input)

                    # Log tool timing
                    log(f"  -> {tool_name} completed in {exec_time_ms:.1f}ms" +
                        (f" [ERROR]" if is_error else ""), "TOOL")

                    # Truncate large outputs
                    if len(output) > 4000:
                        output = output[:4000] + f"\n\n... (truncated, {len(output)} total chars)"

                    tool_result = {
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": output
                    }
                    if is_error:
                        tool_result["is_error"] = True

                    all_tool_results.append(tool_result)

                    # Log execution with timing
                    self.execution_log.append({
                        "timestamp": datetime.now().isoformat(),
                        "batch_id": batch_id,
                        "tool": tool_name,
                        "tool_id": tool_id,
                        "input": tool_input,
                        "output_preview": output[:200],
                        "is_error": is_error,
                        "execution_time_ms": exec_time_ms,
                        "model": model
                    })

        return {
            "stop_reason": final_stop_reason,
            "tool_results": all_tool_results,
            "assistant_content": all_assistant_content,
            "text_output": "\n".join(text_output),
            "custom_id": custom_id,
            "model": model
        }

    def submit_followup_batch(
        self,
        custom_id: str,
        model: str,
        system_prompt: str,
        messages: list[dict],
        tool_results: list[dict]
    ) -> str:
        """
        Submit a follow-up batch with tool results.
        Returns the new batch ID.
        """
        # Build the full message history including tool results
        full_messages = messages.copy()

        # Add assistant message with tool uses (from the previous response)
        # Then add user message with tool results
        self.verbose_log(f"[SUBMIT] Adding {len(tool_results)} tool results to follow-up batch", "INFO")
        for i, tr in enumerate(tool_results):
            self.verbose_log(f"[SUBMIT]   Result {i+1}: tool_use_id={tr.get('tool_use_id', '?')}, is_error={tr.get('is_error', False)}", "INFO")

        full_messages.append({
            "role": "user",
            "content": tool_results
        })

        # Create batch request
        batch_request = {
            "custom_id": f"{custom_id}-continue-{self.total_batches_submitted}",
            "params": {
                "model": model,
                "max_tokens": 8192,
                "system": system_prompt,
                "tools": TOOLS,
                "messages": full_messages
            }
        }

        self.verbose_log(f"[SUBMIT] Submitting follow-up batch with {len(full_messages)} messages", "INFO")
        self.verbose_log(f"[SUBMIT] Batch request size: {len(json.dumps(batch_request))} bytes", "INFO")

        batch = self.client.beta.messages.batches.create(
            requests=[batch_request]
        )

        self.total_batches_submitted += 1
        self.verbose_log(f"[SUBMIT] New batch submitted: {batch.id}", "OK")

        return batch.id

    def execute_batch_loop(
        self,
        initial_batch_id: str,
        phase_name: str = "",
        max_iterations: int = 20
    ) -> dict:
        """
        Execute the full tool loop for a batch until end_turn.

        Returns summary dict with stats and final output.
        """
        log("=" * 70)
        log(f"BATCH TOOL LOOP: {initial_batch_id}")
        if phase_name:
            log(f"Phase: {phase_name}")
        log("=" * 70)

        current_batch_id = initial_batch_id
        iteration = 0
        all_text = []
        messages_history = []  # Track conversation for follow-ups

        while iteration < max_iterations:
            iteration += 1
            log(f"--- Iteration {iteration} ---")

            # Process current batch
            result = self.process_batch(current_batch_id, phase_name if iteration == 1 else "")

            if result.get("error"):
                log(f"Error: {result['error']}", "ERR")
                break

            # Collect text output
            if result["text_output"]:
                all_text.append(result["text_output"])

            stop_reason = result["stop_reason"]

            if stop_reason == "end_turn":
                log("Reached end_turn - loop complete", "OK")
                break

            elif stop_reason == "tool_use":
                tool_results = result["tool_results"]
                log(f"Executed {len(tool_results)} tools, continuing...", "INFO")

                # For follow-up, we need to reconstruct the conversation
                # The assistant's content becomes part of the history
                assistant_content = []
                for block in result["assistant_content"]:
                    if block.type == "text":
                        assistant_content.append({"type": "text", "text": block.text})
                    elif block.type == "tool_use":
                        assistant_content.append({
                            "type": "tool_use",
                            "id": block.id,
                            "name": block.name,
                            "input": block.input
                        })

                messages_history.append({"role": "assistant", "content": assistant_content})

                # Submit follow-up batch
                current_batch_id = self.submit_followup_batch(
                    custom_id=result["custom_id"] or "batch-loop",
                    model=result["model"] or "claude-haiku-4-5-20251001",
                    system_prompt="Continue executing the task. You have access to file and command tools.",
                    messages=messages_history,
                    tool_results=tool_results
                )

            elif stop_reason == "max_tokens":
                log("Reached max_tokens - may need to continue", "WAIT")
                # Could submit a continuation batch here
                break

            else:
                log(f"Unexpected stop_reason: {stop_reason}", "ERR")
                break

        # Check for unresolved tool errors
        has_tool_errors = len(self.tool_errors) > 0
        if has_tool_errors:
            log(f"ESCALATION: {len(self.tool_errors)} tool errors encountered:", "ERR")
            for err in self.tool_errors[:5]:  # Show first 5 errors
                log(f"  - {err.get('tool', '?')}: {err.get('error', '?')}", "ERR")
            if len(self.tool_errors) > 5:
                log(f"  ... and {len(self.tool_errors) - 5} more", "ERR")

        return {
            "initial_batch_id": initial_batch_id,
            "phase_name": phase_name,
            "iterations": iteration,
            "total_tools": self.total_tools_executed,
            "text_output": "\n\n".join(all_text),
            "stop_reason": stop_reason,
            "has_tool_errors": has_tool_errors,
            "tool_errors": self.tool_errors.copy(),
            "model": result.get("model") if 'result' in dir() else None
        }

    def verify_phase_success(self, result: dict) -> tuple[bool, str]:
        """
        Verify that a phase completed successfully.

        Returns (success: bool, reason: str).
        Success criteria:
        - stop_reason == "end_turn"
        - No critical tool errors (file operations must succeed)
        """
        stop_reason = result.get("stop_reason", "unknown")

        if stop_reason != "end_turn":
            return False, f"stop_reason={stop_reason}, expected 'end_turn'"

        # Check for critical errors (write_file failures are critical)
        critical_errors = [e for e in result.get("tool_errors", [])
                          if e.get("tool") in ("write_file", "run_command")]
        if critical_errors:
            error_summary = "; ".join([f"{e['tool']}: {e['error'][:50]}" for e in critical_errors[:3]])
            return False, f"Critical tool errors: {error_summary}"

        return True, "Phase completed successfully"

    def execute_phase_with_retry(
        self,
        batch_id: str,
        phase_name: str,
        max_iterations: int = 20,
        system_prompt: Optional[str] = None
    ) -> dict:
        """
        Execute a phase with retry logic and model escalation.

        Returns dict with:
            - success: bool
            - result: the batch loop result
            - attempts: list of (model, attempt_num, success, reason)
            - final_model: which model succeeded (or last tried)
        """
        self.reset_for_phase()
        attempts: list[tuple[str, int, bool, str]] = []

        log("=" * 70)
        log(f"[PHASE] {phase_name}")
        log(f"  Model: {get_model_short_name(self.get_current_model())}")
        log(f"  Max retries: {self.max_retries}")
        log("=" * 70)

        while True:
            current_model = self.get_current_model()
            self.retry_count += 1
            attempt_num = self.retry_count

            log(f"  Attempt {attempt_num}: Model={get_model_short_name(current_model)}", "RETRY")

            # Clear tool errors for this attempt
            self.tool_errors = []

            try:
                result = self.execute_batch_loop(
                    batch_id,
                    phase_name=phase_name,
                    max_iterations=max_iterations
                )

                # Verify phase success
                success, reason = self.verify_phase_success(result)
                attempts.append((get_model_short_name(current_model), attempt_num, success, reason))

                if success:
                    log(f"  Attempt {attempt_num}: SUCCESS", "OK")
                    return {
                        "success": True,
                        "result": result,
                        "attempts": attempts,
                        "final_model": current_model
                    }
                else:
                    log(f"  Attempt {attempt_num}: FAILED ({reason})", "ERR")

            except Exception as e:
                reason = f"Exception: {str(e)}"
                attempts.append((get_model_short_name(current_model), attempt_num, False, reason))
                log(f"  Attempt {attempt_num}: FAILED ({reason})", "ERR")

            # Check if we should escalate
            if self.should_escalate():
                self.escalate_model()
                continue  # Try with new model

            # Check if we've exhausted all options
            if (self.retry_count >= self.max_retries and
                self.current_model_index >= len(ESCALATION_CHAIN) - 1):
                log(f"  All retries and escalations exhausted", "ERR")
                return {
                    "success": False,
                    "result": result if 'result' in dir() else None,
                    "attempts": attempts,
                    "final_model": current_model
                }

            # More retries available with current model
            continue


def main():
    parser = argparse.ArgumentParser(
        description="Execute batch API tool loops with retry and model escalation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python batch_executor.py msgbatch_01JoDGSYgfqHBQqMXh9jnUaK
    python batch_executor.py --all-restructure-phases
    python batch_executor.py --all-restructure-phases --with-retry
    python batch_executor.py --phase=2 --max-retries=3
    python batch_executor.py batch1 batch2 batch3 --sequential

Model Escalation Chain:
    haiku -> sonnet -> opus

When --with-retry is used:
    - Each phase is validated for success (stop_reason="end_turn", no critical tool errors)
    - On failure, retries up to --max-retries times with current model
    - After retries exhausted, escalates to next model in chain
    - If a phase fails after all models exhausted, stops execution (no next phase)
        """
    )

    parser.add_argument(
        "batch_ids",
        nargs="*",
        help="Batch IDs to process"
    )
    parser.add_argument(
        "--all-restructure-phases",
        action="store_true",
        help="Execute all 5 CSC restructure phases"
    )
    parser.add_argument(
        "--phase",
        type=int,
        metavar="N",
        help="Run only phase N (1-5) with retry/escalation logic"
    )
    parser.add_argument(
        "--with-retry",
        action="store_true",
        help="Enable retry logic and model escalation"
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=DEFAULT_MAX_RETRIES,
        help=f"Max retries per model before escalation (default: {DEFAULT_MAX_RETRIES})"
    )
    parser.add_argument(
        "--sequential",
        action="store_true",
        default=True,
        help="Process batches sequentially (default)"
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=20,
        help="Max tool loop iterations per batch (default: 20)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be executed without running"
    )

    args = parser.parse_args()

    # Define restructure phases
    ALL_PHASES = [
        ("msgbatch_01JoDGSYgfqHBQqMXh9jnUaK", "Phase 1: Stop & Uninstall"),
        ("msgbatch_01MEAQxvNL69HAbPDYsuaeR3", "Phase 2: Execute Restructure"),
        ("msgbatch_01YENeceG7qXCu6WaVu9VxXs", "Phase 3: Reinstall & Verify"),
        ("msgbatch_01VR2ZAWYhvXFtgovqYmy88H", "Phase 4: Start Services"),
        ("msgbatch_01HTVWVLazaYVfL7Lg8BeiAu", "Phase 5: Final Verification"),
    ]

    # Determine batch IDs to process
    if args.phase:
        if args.phase < 1 or args.phase > len(ALL_PHASES):
            log(f"Invalid phase number: {args.phase}. Valid range: 1-{len(ALL_PHASES)}", "ERR")
            sys.exit(1)
        batch_ids = [ALL_PHASES[args.phase - 1]]
        # Single phase implies retry mode
        args.with_retry = True
    elif args.all_restructure_phases:
        batch_ids = ALL_PHASES
    elif args.batch_ids:
        batch_ids = [(bid, f"Batch {i+1}") for i, bid in enumerate(args.batch_ids)]
    else:
        parser.print_help()
        sys.exit(1)

    if args.dry_run:
        print("\n=== DRY RUN ===")
        print("Would process the following batches:")
        for batch_id, phase in batch_ids:
            print(f"  - {batch_id}: {phase}")
        sys.exit(0)

    # Initialize executor
    try:
        api_key = get_api_key()
        log("API key loaded", "OK")
    except Exception as e:
        log(f"Failed to get API key: {e}", "ERR")
        sys.exit(1)

    executor = BatchToolExecutor(api_key, max_retries=args.max_retries)

    # Execute batches
    print("\n" + "=" * 70)
    print("BATCH API TOOL LOOP EXECUTOR - CSC RESTRUCTURE")
    print("=" * 70)
    print(f"Batches to process: {len(batch_ids)}")
    print(f"Max iterations per batch: {args.max_iterations}")
    if args.with_retry:
        print(f"Retry mode: ENABLED (max_retries={args.max_retries})")
        print(f"Escalation chain: haiku -> sonnet -> opus")
    print("=" * 70 + "\n")

    results = []
    start_time = time.time()
    phase_failed = False

    for batch_id, phase_name in batch_ids:
        # Skip remaining phases if a previous phase failed
        if phase_failed:
            log(f"Skipping {phase_name} - previous phase failed", "ERR")
            results.append({
                "initial_batch_id": batch_id,
                "phase_name": phase_name,
                "skipped": True,
                "error": "Previous phase failed"
            })
            continue

        try:
            if args.with_retry:
                # Use retry/escalation logic
                phase_result = executor.execute_phase_with_retry(
                    batch_id,
                    phase_name=phase_name,
                    max_iterations=args.max_iterations
                )
                result = phase_result.get("result", {})
                result["attempts"] = phase_result.get("attempts", [])
                result["final_model"] = phase_result.get("final_model")
                result["phase_success"] = phase_result.get("success", False)

                if not phase_result.get("success"):
                    phase_failed = True
                    log(f"Phase failed: {phase_name} - stopping execution", "ERR")

                results.append(result)
            else:
                # Simple mode - no retry/escalation
                result = executor.execute_batch_loop(
                    batch_id,
                    phase_name=phase_name,
                    max_iterations=args.max_iterations
                )
                results.append(result)

        except Exception as e:
            log(f"Error processing {batch_id}: {e}", "ERR")
            import traceback
            traceback.print_exc()
            results.append({
                "initial_batch_id": batch_id,
                "phase_name": phase_name,
                "error": str(e)
            })
            phase_failed = True

    elapsed = time.time() - start_time

    # Summary
    print("\n" + "=" * 70)
    print("EXECUTION COMPLETE")
    print("=" * 70)
    print(f"Total time: {elapsed:.1f}s")
    print(f"Total batches submitted: {executor.total_batches_submitted}")
    print(f"Total tools executed: {executor.total_tools_executed}")
    print("")

    for result in results:
        phase = result.get("phase_name", "Unknown")
        if result.get("skipped"):
            print(f"  {phase}: SKIPPED (previous phase failed)")
        elif "error" in result:
            print(f"  {phase}: ERROR - {result['error']}")
        else:
            # Show retry/escalation info if available
            attempts = result.get("attempts", [])
            final_model = result.get("final_model")
            phase_success = result.get("phase_success")

            status = "SUCCESS" if phase_success else "FAILED" if phase_success is False else ""
            model_info = f" [{get_model_short_name(final_model)}]" if final_model else ""
            retry_info = f" ({len(attempts)} attempts)" if attempts else ""

            print(f"  {phase}: {result.get('iterations', 0)} iterations, "
                  f"{result.get('total_tools', 0)} tools{model_info}{retry_info}"
                  f"{' - ' + status if status else ''}")

    print("=" * 70)

    # Verify expected project layout
    print("\nVerifying project paths...")
    print(f"  {CSC_ROOT / 'irc'} exists: {(CSC_ROOT / 'irc').exists()}")
    print(f"  {CSC_ROOT / 'ops'} exists: {(CSC_ROOT / 'ops').exists()}")

    # Save execution log
    log_file = LOGS_DIR / f"batch_executor_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(log_file, "w") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "batches_processed": len(batch_ids),
            "total_tools_executed": executor.total_tools_executed,
            "total_batches_submitted": executor.total_batches_submitted,
            "elapsed_seconds": elapsed,
            "execution_log": executor.execution_log,
            "results": [
                {k: v for k, v in r.items() if k != "text_output"}
                for r in results
            ]
        }, f, indent=2, default=str)

    log(f"Execution log saved to: {log_file}", "OK")

    # CRITICAL: Exit with failure code if any phase failed or tools had errors
    if phase_failed or executor.tool_errors:
        print("\n[EXIT] Phase had failures or tool errors - exiting with code 1")
        log(f"FAILURE: phase_failed={phase_failed}, tool_errors={len(executor.tool_errors)}", "ERR")
        sys.exit(1)
    else:
        print("\n[EXIT] All phases completed successfully - exiting with code 0")
        sys.exit(0)


if __name__ == "__main__":
    main()
