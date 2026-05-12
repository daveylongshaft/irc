---
slug: ascii-only
name: ASCII-only in all files
description: Never use non-ASCII characters in any file output -- no emoji, no Unicode dashes or arrows.
type: feedback
status: reference
tags: [feedback, files, encoding]
related: []
updated: 2026-04-10T00:00:00Z
---

Never use any character outside 7-bit ASCII (0-127) in files, especially configuration, code, and documentation.

**Why:** Non-ASCII causes issues with log parsing, system tools, and cross-platform compatibility.

**How to apply:**
- Replace emoji with text: checkmarks -> [OK], failures -> [FAIL], todos -> [TODO]
- Replace em-dash with hyphen (-)
- Replace Unicode arrows with ASCII arrows (->)
- Use only basic punctuation: . , ; : ! ? ' " - / \ ( ) [ ] { }
- Letters A-Z a-z, digits 0-9, and common symbols only
