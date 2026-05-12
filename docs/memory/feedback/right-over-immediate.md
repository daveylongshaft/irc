---
slug: right-over-immediate
name: Right solution over immediate solution
description: Always choose the architecturally correct approach; never build scaffolding then offer to upgrade it.
type: feedback
status: reference
tags: [feedback, architecture, approach]
related: [oo-containerization]
updated: 2026-04-12T00:00:00Z
---

Pick the right option over any immediate solution, always. Do not build a quickfix and then offer to upgrade it -- that is still doing the quickfix first, just with extra words.

**Why:** Davey has repeatedly caught a specific failure pattern: partial scaffolding that does most of the job the quick way, then "do you want me to do it properly?" That shape is wrong. The right shape was to do it properly from the first line of code.

**How to apply:**
- Spend the thinking budget BEFORE the first edit to find the architecturally correct shape.
- If mid-coding you notice a shortcut approaching (identity-by-tuple, parallel dicts, stub-then-upgrade), STOP and redesign.
- Do not present a choice between quickfix-now and proper-later. Skip the offer.
- Exception: if the proper approach needs information you don't have, ask ONE clarifying question up front before any code, then go straight to the proper build.
- Test: would Davey tear this out the moment he sees it? If yes, it is the quickfix. Do not commit it.
