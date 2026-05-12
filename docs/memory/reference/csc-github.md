---
slug: csc-github
name: CSC GitHub repository
description: Central CSC repo at github.com/daveylongshaft/csc.git; clone with --recurse-submodules.
type: reference
status: reference
tags: [reference, git, csc, github]
related: [temp-clone-git-workflow]
updated: 2026-05-05T00:00:00Z
---

Repository: https://github.com/daveylongshaft/csc.git

Clone with submodules: `git clone --recurse-submodules https://github.com/daveylongshaft/csc.git`

Includes the main csc.git repo (Python packages in irc/packages/) and the irc.git submodule.

Package structure:
- /irc/packages/csc-<service>/ -- Python packages (pyproject.toml + source dir)
- /irc/packages/csc-eggdrop/ -- Eggdrop/Tcl scripts

Implementation work: always clone to /c/csc/tmp/clones/csc, create a feature branch, work there, push, open PR. Never commit directly to main.
