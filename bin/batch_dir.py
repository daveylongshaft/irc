#!env /usr/bin/python3
"""
batch_dir.py - Execute all workorders in a directory sequentially via Batch API

Takes a directory path, finds all .md workorder files, and executes them in order
using Anthropic Batch API with full tool loop support.

Usage:
    python3 batch_dir.py /path/to/workorders/
    python3 batch_dir.py "$CSC_OPS_WO/ready" --max-retries 3
"""

import os
import sys
import argparse
import subprocess
import json
from pathlib import Path
from datetime import datetime

try:
    from csc_service.shared.platform import Platform
    PLATFORM = Platform()
    CSC_ROOT = Path(PLATFORM.get_abs_root_path([]))
except Exception:
    PLATFORM = None
    CSC_ROOT = Path(__file__).resolve().parents[2]

def get_api_key():
    """Get API key from .env or environment."""
    env_file = CSC_ROOT / ".env"
    if env_file.exists():
        content = env_file.read_text()
        for line in content.split("\n"):
            if "ANTHROPIC_API_KEY_3=" in line and "sk-" in line:
                return line.split('"')[1]

    # Fallback to environment
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key

    raise RuntimeError("ANTHROPIC_API_KEY not found in .env or environment")


def submit_workorder_batch(wo_file, api_key):
    """Submit a workorder as a batch via Anthropic API."""
    import anthropic

    # Read workorder
    with open(wo_file, 'r') as f:
        content = f.read()

    # Parse workorder (simple format: first line is title/prompt, rest is instructions)
    lines = content.split('\n', 1)
    system_prompt = lines[0] if lines else "Execute task"
    user_prompt = lines[1] if len(lines) > 1 else "Proceed with task"

    # Create batch request
    client = anthropic.Anthropic(api_key=api_key)

    batch_request = {
        "custom_id": f"wo-{Path(wo_file).stem}",
        "params": {
            "model": "claude-opus-4-20250514",
            "max_tokens": 16384,
            "system": system_prompt,
            "tools": [
                {
                    "name": "run_command",
                    "description": "Execute bash command",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "command": {"type": "string", "description": "Bash command to execute"}
                        },
                        "required": ["command"]
                    }
                },
                {
                    "name": "read_file",
                    "description": "Read file contents",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "File path"}
                        },
                        "required": ["path"]
                    }
                },
                {
                    "name": "write_file",
                    "description": "Write file contents",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "File path"},
                            "content": {"type": "string", "description": "File content"}
                        },
                        "required": ["path", "content"]
                    }
                },
                {
                    "name": "list_directory",
                    "description": "List directory contents",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Directory path"}
                        },
                        "required": ["path"]
                    }
                }
            ],
            "messages": [
                {
                    "role": "user",
                    "content": user_prompt
                }
            ]
        }
    }

    # Submit batch
    batch = client.beta.messages.batches.create(requests=[batch_request])
    return batch.id


def run_batch_executor(batch_id, max_retries=2):
    """Run batch executor for a batch ID."""
    env = os.environ.copy()
    if "ANTHROPIC_API_KEY" not in env:
        env["ANTHROPIC_API_KEY"] = get_api_key()

    executor_path = Path(__file__).resolve().with_name("batch_executor.py")

    cmd = [
        "python3",
        str(executor_path),
        batch_id,
        f"--max-retries={max_retries}"
    ]

    result = subprocess.run(cmd, env=env, capture_output=False, text=True)
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(
        description="Execute all workorders in a directory sequentially via Batch API"
    )
    parser.add_argument("directory", help="Directory containing .md workorder files")
    parser.add_argument("--max-retries", type=int, default=2, help="Max retries per workorder")
    parser.add_argument("--pattern", default="*.md", help="File pattern to match (default: *.md)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would run without executing")
    parser.add_argument("--skip-failed", action="store_true", help="Continue even if a workorder fails")

    args = parser.parse_args()

    # Validate directory
    wo_dir = Path(args.directory)
    if not wo_dir.is_dir():
        print(f"ERROR: {args.directory} is not a directory", file=sys.stderr)
        return 1

    # Find workorders
    workorders = sorted(wo_dir.glob(args.pattern))
    if not workorders:
        print(f"ERROR: No workorder files matching '{args.pattern}' in {wo_dir}", file=sys.stderr)
        return 1

    print("=" * 80)
    print(f"BATCH DIRECTORY EXECUTOR")
    print("=" * 80)
    print(f"Directory: {wo_dir}")
    print(f"Workorders: {len(workorders)}")
    print(f"Max retries: {args.max_retries}")
    print()

    # List workorders
    for i, wo in enumerate(workorders, 1):
        print(f"{i:2d}. {wo.name}")

    if args.dry_run:
        print("\n(Dry run - no execution)")
        return 0

    print("\n" + "=" * 80)

    # Get API key
    try:
        api_key = get_api_key()
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    # Execute workorders sequentially
    results = {}
    failed = []

    for i, wo_file in enumerate(workorders, 1):
        wo_name = wo_file.stem
        print(f"\n[{i}/{len(workorders)}] {wo_name}")
        print("-" * 80)

        try:
            # Submit batch
            print(f"Submitting batch...")
            batch_id = submit_workorder_batch(str(wo_file), api_key)
            print(f"Batch ID: {batch_id}")

            # Run executor
            print(f"Executing batch (max retries: {args.max_retries})...")
            success = run_batch_executor(batch_id, args.max_retries)

            results[wo_name] = {
                "status": "SUCCESS" if success else "FAILED",
                "batch_id": batch_id,
                "timestamp": datetime.now().isoformat()
            }

            if not success:
                failed.append(wo_name)
                if not args.skip_failed:
                    print(f"\nERROR: Workorder {wo_name} failed")
                    print("Stopping (use --skip-failed to continue)")
                    break
                else:
                    print(f"WARNING: Workorder {wo_name} failed, continuing...")
            else:
                print(f"SUCCESS: Workorder {wo_name} completed")

        except Exception as e:
            print(f"ERROR: {e}", file=sys.stderr)
            results[wo_name] = {
                "status": "ERROR",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
            failed.append(wo_name)
            if not args.skip_failed:
                break

    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total: {len(workorders)}")
    print(f"Success: {len(workorders) - len(failed)}")
    print(f"Failed: {len(failed)}")

    if failed:
        print("\nFailed workorders:")
        for wo in failed:
            batch_id = results[wo].get("batch_id", "?")
            print(f"  - {wo} (batch: {batch_id})")

    # Save results
    results_file = wo_dir / f"batch_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(results_file, 'w') as f:
        json.dump(results, f, indent=2)

    print(f"\nResults saved to: {results_file}")

    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
