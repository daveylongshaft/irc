---
slug: snake-case
name: snake_case everywhere
description: All identifiers including class names use snake_case; overrides Python PEP8 PascalCase convention.
type: feedback
status: reference
tags: [feedback, style, python]
related: []
updated: 2026-05-01T00:00:00Z
---

Use snake_case for all identifiers in code: variables, functions, methods, AND class names. No camelCase, no PascalCase.

**Why:** Davey finds camelCase/PascalCase hard to read. Stated explicitly.

**How to apply:** Even where Python convention says PascalCase (class names, type aliases), use snake_case. e.g., `class character:` not `class Character:`. This overrides PEP8 -- user preference wins. Also applies to file names and references in docs and plans.
