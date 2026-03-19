Role Links Setup
================

The dash-prefixed files (-architect, -worker, -pm, etc.) are symlinks/junctions that point to
role directories in ops/roles/. They are NOT version-controlled (ignored in .gitignore) and are
created locally on each developer's machine.

Why Not Version-Controlled?
---------------------------

- Symlinks work on Linux/Mac but cause issues on Windows in git
- Directory junctions (Windows) don't work on Linux/Mac
- Each OS needs different link types
- Solution: Create links locally on setup, ignore in git

Link Types by OS
----------------

- Linux/Mac: POSIX symlinks (ln -s)
- Windows: Directory junctions (mklink /J) - no admin needed
- Git Bash/MSYS: Same as Windows junctions or symlinks

Mapping
-------

The dash-prefixed names map to role directories:

  -architect    → ops/roles/architect
  -worker       → ops/roles/worker
  -pm           → ops/roles/pm-worker
  -codereview   → ops/roles/code-reviewer
  -debug        → ops/roles/debugger
  -reviewer     → ops/roles/pr-reviewer
  -testfix      → ops/roles/test-fixer

First Time Setup
----------------

After cloning the repository, run the setup script to create local symlinks/junctions:

Linux/Mac:
  bash ./setup-role-links.sh

Windows (Git Bash):
  bash ./setup-role-links.sh

Windows (Command Prompt):
  setup-role-links.bat

The script:
- Auto-detects your OS
- Creates symlinks on Linux/Mac
- Creates directory junctions on Windows
- Reports success/failure for each link

Troubleshooting
---------------

If symlinks don't work after running setup:

Linux/Mac:
  - Verify bash script executed: ls -la -architect
  - Should show: -architect -> ops/roles/architect
  - Try running manually: ln -s ops/roles/architect -architect

Windows (admin needed for mklink):
  - Right-click Command Prompt, select "Run as administrator"
  - Run: setup-role-links.bat
  - Or manually: mklink /J -architect ops\roles\architect

Windows (Git Bash, without admin):
  - Use: bash setup-role-links.sh
  - Falls back to symlinks if junctions fail

Usage
-----

Reference role context in prompts using the dash-prefixed names:

  @-architect/README.md        Load architect role context
  @-worker/README.md           Load worker role context
  @-pm/README.md               Load PM context
  @-codereview/README.md       Load code reviewer context
  etc.

In development, these are just directories at the root:
  /c/csc/-architect/README.md  (Linux/Mac symlink or Windows junction)

Maintenance
-----------

If role directories are renamed or new roles added:
- Update the mapping in setup-role-links.sh and setup-role-links.bat
- Re-run setup scripts on all developer machines
- Old links can be manually deleted: rm -f -* or del /s -.* (Windows)

Git Configuration
------------------

.gitignore includes entries for all dash-prefixed files:

  # Role symlinks / junctions (OS-specific, generated locally)
  -architect
  -architect.lnk
  -worker
  ...

This ensures symlinks/junctions never get committed and won't show up in
git status after setup.

Testing Links
-------------

After setup, test by reading a role file:

  cat -architect/README.md     (Linux/Mac)
  type -architect\README.md    (Windows)

Or check that the link points to the right place:

  ls -ld -architect            (Linux/Mac)
  dir -architect               (Windows)
