#!/usr/bin/env python3
"""Run benchmarks against AI agents and collect results.

Calls the Anthropic Messages API directly with the same tools as run_agent.py
but without queue/git/WIP infrastructure overhead, so timing measures the model.

Usage:
    python benchmarks/run_benchmark.py <benchmark_name> <agent_name> [--runs N]
    python benchmarks/run_benchmark.py all haiku --runs 3
    python benchmarks/run_benchmark.py list
    python benchmarks/run_benchmark.py results [agent]

Examples:
    python benchmarks/run_benchmark.py implement-feature haiku --runs 3
    python benchmarks/run_benchmark.py code-review sonnet --runs 3
    python benchmarks/run_benchmark.py all opus --runs 1
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

BENCHMARKS_DIR = Path(__file__).resolve().parent
PROMPTS_DIR = BENCHMARKS_DIR / "prompts"
RESULTS_DIR = BENCHMARKS_DIR / "results"
METADATA_FILE = BENCHMARKS_DIR / "benchmarks.json"
CSC_ROOT = BENCHMARKS_DIR.parent

# Agent → model mapping (same as run_agent.py)
AGENT_MODELS = {
    "haiku":  "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-6",
    "opus":   "claude-opus-4-6",
}

MAX_TOKENS = {
    "claude-opus-4-6": 32768,
    "claude-sonnet-4-6": 32768,
    "claude-haiku-4-5-20251001": 8192,
}

MAX_TURNS = 50  # Benchmark tasks should complete in fewer turns


def load_metadata():
    if METADATA_FILE.exists():
        return json.loads(METADATA_FILE.read_text(encoding="utf-8"))
    return {}


def save_metadata(data):
    METADATA_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def list_benchmarks():
    """List available benchmark prompts."""
    prompts = sorted(PROMPTS_DIR.glob("*.md"))
    if not prompts:
        print("No benchmarks found in benchmarks/prompts/")
        return []
    names = []
    for p in prompts:
        name = p.stem
        names.append(name)
        content = p.read_text(encoding="utf-8")
        desc = ""
        for line in content.splitlines():
            if line.startswith("## Description"):
                continue
            if line.strip() and not line.startswith("#"):
                desc = line.strip()[:80]
                break
        print(f"  {name:30s} {desc}")
    return names


def _import_tools():
    """Import tool functions from run_agent.py."""
    agent_runner = CSC_ROOT / "agents" / "templates" / "run_agent.py"
    if not agent_runner.exists():
        print(f"ERROR: {agent_runner} not found")
        sys.exit(1)

    import importlib.util
    spec = importlib.util.spec_from_file_location("run_agent", str(agent_runner))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_single(benchmark_name: str, agent_name: str, run_agent_mod) -> dict:
    """Run a single benchmark with an agent via the Anthropic API.

    Uses the same tools and system prompt as run_agent.py but without
    the queue-worker infrastructure (git pull, WIP files, etc.).
    """
    from anthropic import Anthropic

    prompt_file = PROMPTS_DIR / f"{benchmark_name}.md"
    if not prompt_file.exists():
        print(f"ERROR: Benchmark prompt not found: {prompt_file}")
        return None

    prompt_content = prompt_file.read_text(encoding="utf-8")
    model = AGENT_MODELS.get(agent_name)
    if not model:
        print(f"ERROR: Unknown agent '{agent_name}'. Available: {', '.join(AGENT_MODELS)}")
        return None

    max_tokens = MAX_TOKENS.get(model, 16384)
    unix_ts = int(time.time())

    # Build tools and system prompt from run_agent.py
    tools = run_agent_mod.build_tools()

    # Minimal system prompt for benchmarks (no WIP journaling needed)
    system = [{
        "type": "text",
        "text": (
            "You are an AI coding agent working on the CSC project.\n"
            "Your working directory is the project root.\n"
            "You have tools to read files, write files, edit files, run bash commands, "
            "glob for file patterns, and grep for content.\n"
            "Complete the task efficiently. When done, output a brief summary of what you did."
        ),
        "cache_control": {"type": "ephemeral"},
    }]

    user_prompt = (
        f"Complete this benchmark task:\n\n{prompt_content}\n\n"
        f"Work in the project at {CSC_ROOT}. "
        "Do NOT modify any files unless the task explicitly asks you to. "
        "Write your findings/output as text in your final response."
    )

    messages = [{"role": "user", "content": user_prompt}]

    print(f"  Starting: {benchmark_name} with {agent_name} (ts={unix_ts})")
    start_time = time.time()

    client = Anthropic()
    total_input_tokens = 0
    total_output_tokens = 0
    cache_read_tokens = 0
    turn_count = 0
    success = False
    final_text = ""
    error_msg = ""

    try:
        for turn in range(MAX_TURNS):
            turn_count = turn + 1

            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                tools=tools,
                messages=messages,
            )

            # Track tokens
            if hasattr(response, "usage"):
                total_input_tokens += getattr(response.usage, "input_tokens", 0)
                total_output_tokens += getattr(response.usage, "output_tokens", 0)
                cache_read_tokens += getattr(response.usage, "cache_read_input_tokens", 0)

            # Serialize response content for message history
            content_serialized = []
            for block in response.content:
                if block.type == "text":
                    content_serialized.append({"type": "text", "text": block.text})
                    final_text = block.text
                elif block.type == "tool_use":
                    content_serialized.append({
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    })

            messages.append({"role": "assistant", "content": content_serialized})

            if response.stop_reason == "end_turn":
                success = True
                break

            if response.stop_reason == "tool_use":
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        try:
                            result = run_agent_mod.execute_tool(
                                block.name, block.input, CSC_ROOT
                            )
                        except Exception as e:
                            result = f"Tool error: {e}"
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": str(result)[:50000],
                        })
                messages.append({"role": "user", "content": tool_results})
            else:
                # Unexpected stop reason
                break

    except Exception as e:
        error_msg = str(e)[:500]
        print(f"  ERROR: {error_msg}")

    end_time = time.time()
    duration = round(end_time - start_time, 2)

    # Save result
    result_data = {
        "benchmark": benchmark_name,
        "agent": agent_name,
        "model": model,
        "duration": duration,
        "turns": turn_count,
        "timestamp": unix_ts,
        "datetime": datetime.fromtimestamp(unix_ts).isoformat(),
        "success": success,
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
        "cache_read_tokens": cache_read_tokens,
        "error": error_msg,
        "output_preview": final_text[:1000] if final_text else "",
    }

    # Write result file
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    result_file = RESULTS_DIR / f"{benchmark_name}-{duration:.2f}-{agent_name}-{unix_ts}.json"
    result_file.write_text(json.dumps(result_data, indent=2), encoding="utf-8")

    # Update metadata
    meta = load_metadata()
    if benchmark_name not in meta:
        meta[benchmark_name] = {"created": unix_ts, "description": "", "runs": []}
    meta[benchmark_name]["runs"].append({
        "agent": agent_name,
        "duration": duration,
        "turns": turn_count,
        "timestamp": unix_ts,
        "success": success,
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
    })
    save_metadata(meta)

    status = "OK" if success else "FAIL"
    cost_est = (total_input_tokens / 1_000_000) * (AGENT_MODELS.get(agent_name, {}) and 1) + (total_output_tokens / 1_000_000) * 5
    print(f"  Finished: {duration:.1f}s, {turn_count} turns, "
          f"{total_input_tokens}in/{total_output_tokens}out tokens [{status}]")
    return result_data


def show_results(benchmark_name: str = None):
    """Show benchmark results with statistics."""
    meta = load_metadata()
    if not meta:
        print("No benchmark results yet.")
        return

    for name in sorted(meta.keys()):
        if benchmark_name and name != benchmark_name:
            continue
        info = meta[name]
        runs = info.get("runs", [])
        if not runs:
            continue

        print(f"\n{'='*70}")
        print(f"Benchmark: {name}")
        print(f"{'='*70}")

        by_agent = {}
        for r in runs:
            agent = r["agent"]
            if agent not in by_agent:
                by_agent[agent] = []
            by_agent[agent].append(r)

        print(f"\n{'Agent':12s} {'Runs':>5s} {'Avg(s)':>8s} {'Min(s)':>8s} "
              f"{'Max(s)':>8s} {'AvgTurns':>9s} {'AvgIn':>8s} {'AvgOut':>8s} {'OK':>5s}")
        print("-" * 70)

        for agent in sorted(by_agent.keys()):
            agent_runs = by_agent[agent]
            durations = [r["duration"] for r in agent_runs]
            turns = [r.get("turns", 0) for r in agent_runs]
            in_tok = [r.get("input_tokens", 0) for r in agent_runs]
            out_tok = [r.get("output_tokens", 0) for r in agent_runs]
            successes = sum(1 for r in agent_runs if r.get("success", False))
            n = len(durations)

            print(f"{agent:12s} {n:5d} {sum(durations)/n:8.1f} {min(durations):8.1f} "
                  f"{max(durations):8.1f} {sum(turns)/n:9.1f} "
                  f"{sum(in_tok)/n:8.0f} {sum(out_tok)/n:8.0f} {successes:3d}/{n}")


def main():
    parser = argparse.ArgumentParser(description="Run CSC agent benchmarks")
    parser.add_argument("benchmark", nargs="?",
                        help="Benchmark name, 'all', 'list', or 'results'")
    parser.add_argument("agent", nargs="?",
                        help="Agent name (haiku, sonnet, opus)")
    parser.add_argument("--runs", type=int, default=3,
                        help="Number of runs per benchmark (default: 3)")
    args = parser.parse_args()

    if not args.benchmark or args.benchmark == "list":
        print("Available benchmarks:")
        list_benchmarks()
        return

    if args.benchmark == "results":
        show_results(args.agent)
        return

    if not args.agent:
        print("ERROR: Specify an agent. Example: python run_benchmark.py implement-feature haiku")
        return

    if args.agent not in AGENT_MODELS:
        print(f"ERROR: Unknown agent '{args.agent}'. Available: {', '.join(AGENT_MODELS)}")
        return

    # Import tools from run_agent.py (once, reused across runs)
    print("Loading tools from run_agent.py...")
    run_agent_mod = _import_tools()

    # Determine which benchmarks to run
    if args.benchmark == "all":
        benchmarks = [p.stem for p in sorted(PROMPTS_DIR.glob("*.md"))]
    else:
        benchmarks = [args.benchmark]

    total_runs = len(benchmarks) * args.runs
    print(f"Running {len(benchmarks)} benchmark(s) x {args.runs} run(s) = "
          f"{total_runs} total with '{args.agent}'")
    print(f"{'='*70}")

    for bm in benchmarks:
        for run_num in range(1, args.runs + 1):
            print(f"\n[{bm} run {run_num}/{args.runs}]")
            run_single(bm, args.agent, run_agent_mod)
            if run_num < args.runs:
                time.sleep(2)

    print(f"\n{'='*70}")
    print("RESULTS SUMMARY")
    show_results()


if __name__ == "__main__":
    main()
