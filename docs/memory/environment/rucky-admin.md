---
slug: rucky-admin
name: rucky backup admin account
description: Local admin on haven-4346 with blank password, console-only logon, for recovering from a broken davey config.
type: environment
status: reference
tags: [environment, windows, admin, recovery]
related: [server-topology]
updated: 2026-05-09T00:00:00Z
---

Account: rucky. Password: none (blank). Groups: Administrators, Users. Created 2026-05-09.

Blank-password logon works because HKLM\System\CurrentControlSet\Control\Lsa\LimitBlankPasswordUse was set to 0 (intentional security tradeoff). This allows console-only local logon but no RDP or network share.

To use: sign out of davey at physical console, select rucky on lock screen, press Enter (no password). Console only.

To verify: `net user rucky` (status), `net localgroup Administrators` (membership).
