# Workflow Orchestration - Delegate to Gemini

## Context
User wants Qwen working with agent assign. Key constraints:
- **DO NOT code it myself** - use gemini-2.5-flash for everything
- Use the gemini BINARY executable (not .bat or .cmd)
- Send prompts like: `cat readme.1shot agents/gemini-2.5-flash/context/* prompts/wip/task.md | gemini-binary -m gemini-2.5-flash -y -p " "`
- Manage workflow: ready → wip → done
- Verify first one, then make wrapper work with agent assign + prompts assign

## Plan
1. Find gemini binary executable location
2. Set up context in `agents/gemini-2.5-flash/context/` with:
   - Qwen integration requirements
   - Agent wrapper mechanics
   - Debugging context
3. Create prompt in prompts/ready/ for Qwen fix
4. Test gemini-2.5-flash with: `cat readme.1shot agents/gemini-2.5-flash/context/* prompts/wip/task.md | gemini-binary -m gemini-2.5-flash -y -p " "`
5. Verify output, move to done
6. Integrate with agent assign + prompts assign workflow
7. Make wrapper work every time

This is workflow orchestration - Gemini does the coding, I manage the workflow.
