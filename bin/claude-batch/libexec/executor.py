"""Batch API executor with tool loop support."""

import json
import os
import time
import sys
import traceback
from pathlib import Path

try:
    from anthropic import Anthropic
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request
except ImportError:
    print("ERROR: anthropic package required. pip install anthropic", file=sys.stderr)
    sys.exit(1)

from libexec.tools import TOOL_DEFINITIONS, execute_tool
from libexec.common import parse_frontmatter, ensure_env


def _log(msg: str):
    """Print with immediate flush so log files get output in real time."""
    print(msg, flush=True)


def _log_err(msg: str):
    """Print to stderr with immediate flush."""
    print(msg, file=sys.stderr, flush=True)


def _serialize_content(content) -> list[dict]:
    """Convert SDK content blocks to serializable dicts for resubmission.

    The Batches API returns content as SDK objects (TextBlock, ToolUseBlock).
    When we append the assistant turn back into messages for the next round,
    they must be plain dicts.
    """
    serialized = []
    for block in content:
        if block.type == "text":
            serialized.append({"type": "text", "text": block.text})
        elif block.type == "tool_use":
            serialized.append({
                "type": "tool_use",
                "id": block.id,
                "name": block.name,
                "input": block.input,
            })
        else:
            serialized.append({"type": block.type})
    return serialized


def _find_repo_root(start: Path) -> Path:
    """Walk up from start to find .git directory. Returns start if not found."""
    p = start.resolve()
    while p.parent != p:
        if (p / ".git").exists():
            return p
        p = p.parent
    return start.resolve()


class BatchExecutor:
    """Execute workorders via Anthropic Batches API with tool loops."""

    def __init__(self, model: str = "claude-haiku-4-5-20251001", max_rounds: int = 15,
                 poll_interval: int = 15):
        self.model = model
        self.max_rounds = max_rounds
        self.poll_interval = poll_interval
        self.api_key = ensure_env("ANTHROPIC_API_KEY")
        self.client = Anthropic(api_key=self.api_key)

    def execute_workorder(self, wo_path: Path, system_context: str = "") -> bool:
        """Execute single workorder with tool loops.

        Changes cwd to repo root so all tool paths are relative to repo.
        Restores cwd when done.
        """
        repo_root = _find_repo_root(wo_path.parent)
        old_cwd = os.getcwd()
        os.chdir(repo_root)
        _log(f"Working directory: {repo_root}")
        try:
            return self._run_workorder(wo_path, system_context)
        finally:
            os.chdir(old_cwd)

    def _run_workorder(self, wo_path: Path, system_context: str) -> bool:
        """Inner workorder execution loop."""
        wo_text = wo_path.read_text(encoding='utf-8')
        metadata, prompt = parse_frontmatter(wo_text)

        model = metadata.get("model", self.model)
        max_rounds = int(metadata.get("max_rounds", self.max_rounds))

        # System message as content blocks with cache_control on the last block.
        # Prompt caching: 90% discount on cached input, stacked with 50% batch.
        system_blocks = []
        if system_context:
            system_blocks.append({"type": "text", "text": system_context})
        cwd = os.getcwd()
        system_blocks.append({
            "type": "text",
            "text": (
                "You are an AI assistant executing a workorder. "
                "Use provided tools to read files, make changes, run commands, etc. "
                f"The repo root is: {cwd}\n"
                f"Use paths relative to this root (e.g. packages/csc-server/server.py) "
                f"or absolute paths starting with {cwd}/. "
                "Be direct and efficient. Stop only when the workorder is complete."
            ),
            "cache_control": {"type": "ephemeral"},
        })

        _log(f"\n{'='*70}")
        _log(f"Workorder: {wo_path.name}")
        _log(f"Model: {model}")
        _log(f"Max rounds: {max_rounds}")
        _log(f"{'='*70}")

        messages = [{"role": "user", "content": prompt}]
        custom_id = f"wo-{wo_path.stem}"

        for round_num in range(1, max_rounds + 1):
            _log(f"\n--- Round {round_num}/{max_rounds} ---")

            # Submit batch
            try:
                batch = self.client.messages.batches.create(
                    requests=[
                        Request(
                            custom_id=custom_id,
                            params=MessageCreateParamsNonStreaming(
                                model=model,
                                max_tokens=8192,
                                system=system_blocks,
                                messages=messages,
                                tools=TOOL_DEFINITIONS,
                            ),
                        )
                    ]
                )
                batch_id = batch.id
                _log(f"Batch: {batch_id}")
            except Exception as e:
                _log_err(f"ERROR submitting batch: {e}")
                return False

            # Poll until ended
            while True:
                try:
                    batch = self.client.messages.batches.retrieve(batch_id)
                    if batch.processing_status == "ended":
                        break
                    _log(f"  Status: {batch.processing_status} (waiting {self.poll_interval}s...)")
                    time.sleep(self.poll_interval)
                except Exception as e:
                    _log_err(f"ERROR polling batch: {e}")
                    return False

            # Check for batch-level errors
            if batch.request_counts.errored > 0:
                _log_err(f"ERROR: Batch had {batch.request_counts.errored} errored request(s)")

            # Retrieve results
            try:
                result_entry = None
                for r in self.client.messages.batches.results(batch_id):
                    if r.custom_id == custom_id:
                        result_entry = r
                        break

                if not result_entry:
                    _log_err(f"ERROR: No result for custom_id={custom_id}")
                    return False

                res = result_entry.result
                if res.type != "succeeded":
                    if res.type == "errored":
                        _log_err(f"ERROR: Request errored: {res.error}")
                    else:
                        _log_err(f"ERROR: Request {res.type}")
                    return False

                message = res.message
            except Exception as e:
                _log_err(f"ERROR retrieving results: {e}")
                traceback.print_exc()
                return False

            # Process response
            text_parts = []
            tool_blocks = []
            for block in message.content:
                if block.type == "text":
                    text_parts.append(block.text)
                elif block.type == "tool_use":
                    tool_blocks.append(block)

            if text_parts:
                _log(f"Response: {' '.join(text_parts)[:200]}...")

            # Append assistant turn (serialized to dicts)
            messages.append({
                "role": "assistant",
                "content": _serialize_content(message.content),
            })

            # Done if no tool calls
            if message.stop_reason != "tool_use" or not tool_blocks:
                _log(f"\nCOMPLETE (stop_reason={message.stop_reason})")
                if text_parts:
                    _log('\n'.join(text_parts))
                return True

            # Execute tools locally, append results
            tool_results = []
            for tb in tool_blocks:
                _log(f"  Tool: {tb.name}({json.dumps(tb.input)[:80]})")
                output = execute_tool(tb.name, dict(tb.input))
                if len(output) > 30000:
                    output = output[:29000] + "\n...[TRUNCATED]..."
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tb.id,
                    "content": output,
                })
            messages.append({"role": "user", "content": tool_results})

        _log_err(f"WARNING: Max rounds ({max_rounds}) reached without completion")
        return False

    def execute_workorders(self, wo_paths: list[Path], system_context: str = "") -> dict[str, bool]:
        """Execute multiple workorders sequentially."""
        results = {}
        for wo_path in wo_paths:
            try:
                results[wo_path.name] = self.execute_workorder(wo_path, system_context)
            except Exception as e:
                _log_err(f"ERROR executing {wo_path.name}: {e}")
                traceback.print_exc()
                results[wo_path.name] = False
        return results
