---
slug: temp-clone-git-workflow
name: Temp Clone Git Workflow
description: Implementation work goes in C:/csc/tmp/irc on a feature branch; main checkouts are disposable and reset to origin/main periodically.
type: workflow
status: reference
tags: [git, workflow, temp-clone]
related: [davey-collaboration-preferences]
updated: 2026-04-06T17:51:18Z
---

Do implementation work in C:/csc/tmp/irc on a feature branch. Push and open a PR back to main. Never rely on C:/csc, C:/csc/irc, or C:/fahu to retain unmerged changes -- a periodic script resets them to origin/main.
