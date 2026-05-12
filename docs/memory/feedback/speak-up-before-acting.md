---
slug: speak-up-before-acting
name: Speak up when an instruction will break something obvious
description: If you can see that an instruction will break existing functionality, say so before executing -- propose a solution that achieves the goal without the breakage.
type: feedback
status: reference
tags: [feedback, communication, approach]
related: [right-over-immediate, attention-to-detail]
expires: 2028-05-12
---

When Davey gives an instruction and you can already see it will break something -- because you understand both the goal AND the system -- say so before executing. Do not silently implement the instruction and let him discover the problem later.

**Why:** During the memory system migration, Davey asked for a one-line pointer in MEMORY.md. The goal (unified CSC store) was clear. The breakage (Claude Code auto-load requires the full catalog in MEMORY.md, not a pointer) was also clear. Both facts were available. The right move was to say "that approach breaks auto-load, here is how we get what you want without that problem" -- before writing anything.

**How to apply:**
- If you can see that an instruction breaks something, stop and say so before any tool calls. Do not proceed and clean up afterward.
- You do not need to have the fix ready before speaking up. Pointing out the breakage IS the value. A fire you warn about is better than a fire you set and then put out.
- Broken-then-fixed is not progress. It is churn. Davey's goal is getting things done, not managing fires you started.
- Do not use "I knew what you wanted" as a reason to skip the warning. That is exactly when the warning is most needed.
