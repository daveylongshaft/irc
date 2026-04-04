#!/usr/bin/env python3
"""Run workorder(s) via Anthropic Batches API with tool loop support.

Usage:
    # From repo root, run single workorder
    batch_run workorder.md

    # Run all workorders in directory
    batch_run ops/wo/s2s_batch/

    # With custom system context
    batch_run workorder.md --context-dir ./my_context/

    # Override model or max rounds
    batch_run workorder.md --model claude-sonnet-4-6 --max-rounds 20
"""

import sys
import os
import argparse
from pathlib import Path

# Ensure unbuffered output so log files get content in real time
os.environ["PYTHONUNBUFFERED"] = "1"

# Import libexec modules
sys.path.insert(0, str(Path(__file__).parent))

from libexec.common import ensure_env, load_system_context, collect_workorders
from libexec.executor import BatchExecutor


def main():
    parser = argparse.ArgumentParser(
        description="Run workorder(s) with Anthropic Batches API and tool loops"
    )
    parser.add_argument(
        "source",
        help="Workorder .md file or directory of .md files"
    )
    parser.add_argument(
        "--context-dir",
        type=Path,
        help="Directory with context files to prepend to system prompt"
    )
    parser.add_argument(
        "--model",
        default="claude-haiku-4-5-20251001",
        help="Claude model (default: haiku for speed/cost)"
    )
    parser.add_argument(
        "--max-rounds",
        type=int,
        default=15,
        help="Max tool loop rounds per workorder (default: 15)"
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=15,
        help="Seconds between status polls (default: 15)"
    )

    args = parser.parse_args()

    # Load API key from environment or .env files
    api_key = ensure_env("ANTHROPIC_API_KEY")
    source = "environment" if "ANTHROPIC_API_KEY" in os.environ else ".env file"
    print(f"Using API key from: {source}", flush=True)

    # Collect workorder files
    workorders = collect_workorders(args.source)
    if not workorders:
        print("ERROR: No workorder files found", file=sys.stderr, flush=True)
        sys.exit(1)

    print(f"Found {len(workorders)} workorder(s):", flush=True)
    for wo in workorders:
        print(f"  - {wo.name}", flush=True)

    # Load system context (same for all WOs for cache hits)
    system_context = ""
    if args.context_dir:
        system_context = load_system_context(args.context_dir)
        print(f"Loaded context from: {args.context_dir}", flush=True)

    # Create executor and run
    executor = BatchExecutor(
        model=args.model,
        max_rounds=args.max_rounds,
        poll_interval=args.poll_interval
    )

    # Execute all workorders
    results = executor.execute_workorders(workorders, system_context)

    # Report results
    print(f"\n{'='*70}", flush=True)
    print("SUMMARY", flush=True)
    print(f"{'='*70}", flush=True)
    for name, success in results.items():
        status = "[OK]" if success else "[FAIL]"
        print(f"{status}  {name}", flush=True)

    # Exit with appropriate code
    failed = sum(1 for s in results.values() if not s)
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
