#!/usr/bin/env python3
"""Sequential batch runner: process multiple workorders one-at-a-time with blocking.

Each workorder:
  1. Submit to Anthropic Batch API
  2. Poll until complete
  3. Execute tool calls locally (loops until stop_reason != tool_use)
  4. BLOCK until finished
  5. Only then start next workorder

This ensures strict ordering and allows dependencies between workorders.

Usage:
    cbatch_sequential.py /opt/csc/ops/wo/ready/*.md
    cbatch_sequential.py --config batch_config.json
    cbatch_sequential.py --glob 'ops/wo/ready/*.md'
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Import executor to get the sequential run() function
_CLAUDE_BATCH_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_CLAUDE_BATCH_DIR))

from cbatch_executor import run


def main():
    parser = argparse.ArgumentParser(
        description="Run workorders sequentially via Anthropic Batch API (blocking tool loops)"
    )
    parser.add_argument("workorders", nargs="*", help="Workorder .md files (glob supported)")
    parser.add_argument("--glob", help="Glob pattern to find workorders")
    parser.add_argument("--config", help="Load workorder paths from batch_config.json")
    parser.add_argument("--model", help="Model override for all workorders")
    parser.add_argument("--max-rounds", type=int, default=15, help="Max tool loop rounds per workorder")
    parser.add_argument("--poll-interval", type=int, default=15, help="Seconds between batch polls")
    args = parser.parse_args()

    # Collect workorder paths
    workorder_paths = []

    # From explicit args
    if args.workorders:
        for pattern in args.workorders:
            p = Path(pattern)
            if "*" in pattern or "?" in pattern:
                # Glob pattern
                base = p.parent if p.parent != Path(".") else Path(".")
                for f in base.glob(p.name):
                    if f.is_file():
                        workorder_paths.append(f)
            elif p.is_file():
                workorder_paths.append(p)

    # From --glob
    if args.glob:
        base = Path(".")
        for f in base.glob(args.glob):
            if f.is_file() and f not in workorder_paths:
                workorder_paths.append(f)

    # From --config
    if args.config:
        import json
        cfg_path = Path(args.config)
        if cfg_path.exists():
            with cfg_path.open() as f:
                cfg = json.load(f)
                for entry in cfg.get("entries", []):
                    prompt_file = entry.get("prompt_file")
                    if prompt_file:
                        p = Path(prompt_file)
                        if p not in workorder_paths:
                            workorder_paths.append(p)

    if not workorder_paths:
        print("ERROR: No workorders found", file=sys.stderr)
        parser.print_help()
        sys.exit(1)

    workorder_paths.sort()
    print(f"\n{'='*60}")
    print(f"Sequential Batch Runner")
    print(f"{'='*60}")
    print(f"Workorders to process (in order): {len(workorder_paths)}\n")
    for i, wo in enumerate(workorder_paths, 1):
        print(f"  {i}. {wo}")

    print(f"\n{'='*60}\n")

    # Process each workorder sequentially (blocking)
    results = {}
    failed_count = 0

    for idx, wo_path in enumerate(workorder_paths, 1):
        print(f"\n[{idx}/{len(workorder_paths)}] Processing: {wo_path.name}")
        try:
            success = run(
                str(wo_path),
                model=args.model,
                max_rounds=args.max_rounds,
                poll_interval=args.poll_interval
            )
            results[str(wo_path)] = "DONE" if success else "FAIL"
            if not success:
                failed_count += 1
        except Exception as e:
            print(f"ERROR: {e}", file=sys.stderr)
            results[str(wo_path)] = "ERROR"
            failed_count += 1

    # Summary
    print(f"\n\n{'='*60}")
    print(f"BATCH SUMMARY")
    print(f"{'='*60}")
    passed = len(workorder_paths) - failed_count
    print(f"Processed: {len(workorder_paths)}")
    print(f"Passed:    {passed}")
    print(f"Failed:    {failed_count}")
    print(f"{'='*60}\n")

    for wo_path, status in results.items():
        symbol = "✓" if status == "DONE" else "✗"
        print(f"  {symbol} {Path(wo_path).name:50} {status}")

    sys.exit(0 if failed_count == 0 else 1)


if __name__ == "__main__":
    main()
