---
slug: no-ssh
name: No SSH by default
description: Do not initiate SSH or remote commands by default; a direct instruction for a specific remote task overrides this for that task only.
type: feedback
status: reference
tags: [feedback, ssh, remote]
related: []
updated: 2026-05-01T00:00:00Z
---

Default: do not initiate SSH/scp/remote commands. Davey manages remote deployments.

**Override:** A direct instruction to do a specific remote action ("grab X off well", "scp the file", "ssh and check Y") overrides this for the duration of THAT task only. After the task completes, resume the default.

**Why:** Davey stated: "If I give you a direct instruction to do a thing it supersedes all prior directives for the duration of work you do on that particular task." This pattern applies to any standing preference, not just SSH.

**How to apply:** When given a specific remote command, just do it. Don't ask permission again within the same task scope. Don't generalize the override to unrelated future tasks.
