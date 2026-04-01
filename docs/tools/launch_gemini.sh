#!/bin/bash
# Launch Gemini agent on a WIP task with proper journaling enforcement
# Usage: bash tools/launch_gemini.sh <WIP_FILENAME>
# Example: bash tools/launch_gemini.sh PROMPT_fix_test_integration.md

set -e
cd /opt/csc

WIP_FILE="$1"
if [ -z "$WIP_FILE" ]; then
    echo "Usage: $0 <WIP_FILENAME>"
    echo "Example: $0 PROMPT_fix_test_integration.md"
    exit 1
fi

WIP_PATH="/opt/csc/prompts/wip/${WIP_FILE}"
if [ ! -f "$WIP_PATH" ]; then
    echo "ERROR: WIP file not found: $WIP_PATH"
    exit 1
fi

# Read the WIP file content
WIP_CONTENT=$(cat "$WIP_PATH")

# Read project context files
CLAUDE_MD=$(cat /opt/csc/CLAUDE.md 2>/dev/null || echo "No CLAUDE.md found")
GEMINI_CTX=$(cat /opt/csc/tools/gemini_context.md 2>/dev/null || echo "No prior reviews.")

PROMPT=$(cat <<ENDPROMPT
=== PAST PERFORMANCE REVIEWS — READ AND APPLY THESE LESSONS ===
${GEMINI_CTX}

=== MANDATORY RULES ===

JOURNALING — NON-NEGOTIABLE:
Before EVERY action (reading a file, editing code, running a command), you MUST first run:
  echo '<detailed description of what you are about to do and why>' >> ${WIP_PATH}

This is the owner's paid work receipt. Every echo must be informative enough that a reader understands the problem and progress WITHOUT reading source code. Bad: "reading server.py". Good: "reading server.py:persist_all() to check if clients_lock is held during JSON writes — test traceback shows KeyError during dict iteration".

WORKFLOW:
1. Read tools/INDEX.txt and the relevant tools/<package>.txt code map FIRST — find the exact file and method before opening .py files
2. Read the WIP task file fully
3. Read the test log to get the exact error traceback
4. Journal + fix the code (NOT the tests, unless the test is wrong)
5. NEVER run tests — cron runs them for free
6. Delete the old test log so cron retests: rm tests/logs/test_<name>.log
7. Commit: git add <changed files> && git commit -m '<description>'
8. PUSH: git push (MANDATORY — verify with: git log origin/main..HEAD should show nothing)
9. Move to done: mv ${WIP_PATH} /opt/csc/prompts/done/${WIP_FILE}
10. Do NOT add Co-Authored-By or AI attribution to commits

CRITICAL: Do NOT work on any task other than ${WIP_FILE}. Stay focused.
CRITICAL: Do NOT modify files outside the scope of this task.
CRITICAL: Always push. Always delete the test log. Always verify push.

=== PROJECT CONTEXT (CLAUDE.md) ===
${CLAUDE_MD}

=== YOUR TASK (${WIP_FILE}) ===
${WIP_CONTENT}
ENDPROMPT
)

echo "Launching Gemini on: ${WIP_FILE}"
echo "WIP path: ${WIP_PATH}"

exec gemini -y -p "$PROMPT"
