Git Workflow & Best Practices
=============================

Complete guide to using git properly in the CSC project. This covers both interactive
development and headless agent work.

GOLDEN RULES
============

1. ALWAYS run refresh-maps before committing code changes
   - Maps are read by agents to find code
   - Stale maps = wasted agent time on dead code paths
   - Takes <5 seconds: refresh-maps --quick

2. NEVER force-push to main
   - Force push rewrites history and loses work
   - Use regular push or rebase on your branch

3. NEVER include AI attribution in commits
   - Commits represent YOUR decisions, not AI work
   - AI work is logged in contrib.txt (separate file)
   - Format: "Add feature X" not "Claude: add feature X"

4. ALWAYS review changes before committing
   - Use git diff to see what changed
   - Use git status to see untracked files
   - Don't commit things you didn't write

5. ALWAYS create focused commits
   - One feature/fix per commit
   - Don't mix refactoring with new features
   - Clear, descriptive commit messages (see format below)

COMMIT MESSAGE FORMAT
=====================

Good commit messages have 3 parts:

1. Type (one word):
   - feat:    New feature or capability
   - fix:     Bug fix
   - refactor: Code reorganization (no behavior change)
   - chore:   Maintenance (dependencies, cleanup, non-code)
   - test:    Test additions or fixes
   - docs:    Documentation
   - perf:    Performance optimization

2. Scope (optional, in parentheses):
   - Affected component: server, agents, storage, queue-worker, etc.
   - e.g., "feat(server)" or "fix(queue-worker)"

3. Subject (clear, concise, imperative):
   - First letter lowercase
   - Present tense: "add" not "added"
   - <70 characters total
   - No period at end

Examples:

  ✓ feat(server): add automatic channel mode persistence
  ✓ fix: handle malformed IRC messages gracefully
  ✓ docs: update installation instructions
  ✓ refactor(storage): simplify JSON atomic write pattern
  ✓ test: add tests for new ban system
  ✓ chore: update dependencies

Bad examples:

  ✗ "fixed bug"                           (vague, wrong format)
  ✗ "Claude: implemented new feature"     (AI attribution)
  ✗ "WIP"                                 (not descriptive)
  ✗ "Feat: Add new feature"               (capital F, line too long)

COMMIT BODY (optional, for complex changes)
============================================

For significant changes, add a blank line after the subject and explain WHY:

  feat(server): add automatic channel mode persistence

  When users set channel modes (e.g., +m, +n), those modes are now
  automatically persisted to channels.json. Previously they were lost
  on server restart. This matches RFC 2812 expectations and makes
  the system more reliable.

Keep the body under 72 characters per line. Explain the motivation, not
the implementation (code speaks for itself).

WORKFLOW: INTERACTIVE DEVELOPER
==============================

You're working on the project interactively (not as an agent).

1. Start a branch
  git checkout -b feature/description
  (Use present tense: feature/add-oper-notifications, feature/fix-privmsg-routing)

2. Make changes
  Edit files, test locally, repeat

3. Before committing (CRITICAL)
  refresh-maps                 Regenerate code maps
  git status                   Review changes
  git diff <file>              Check specific files

4. Commit
  git add <file1> <file2>      Stage specific files (not git add -A)
  git commit -m "feat: description"

5. Push and PR
  git push -u origin feature/...
  gh pr create --title "..." --body "..."
  (Assign to Opus or Gemini-3-Pro for review)

6. After approval, merge
  gh pr merge                  Merges and deletes branch

WORKFLOW: HEADLESS AGENT
=======================

An agent (background process) is working on a workorder.

Agent's Git Responsibilities:

1. Refresh maps BEFORE starting work
  echo 'refresh-maps --quick' >> $CSC_AGENT_REPO/run_agent.py
  (Or do this first in the prompt)

2. Stage specific files
  git add <file1> <file2>     NOT git add -A (avoids accidental commits)

3. Commit with clear message
  git commit -m "fix(server): handle empty privmsg"
  (Follow format above)

4. Push to branch
  git push origin <branch>    (Branch name matches workorder)

5. DO NOT merge PR
  Agent creates PR, but human/reviewer approves + merges
  (Agent shouldn't modify main)

Agent's Limitations:

✗ NEVER force-push
✗ NEVER modify main directly
✗ NEVER git rebase -i (interactive, not supported in headless)
✗ NEVER include git passwords/tokens in commit messages
✗ NEVER run git pull before pushing (causes conflicts in headless)

MERGING & PR REVIEW
===================

Who Can Approve PRs?

  Opus or Gemini-3-Pro (either one, not both)

  These models have full context and authority to approve or request changes.

  Fast iteration:
    - Create PR
    - One review
    - Approve/request changes
    - Merge when ready

Reviewer's Checklist

  [ ] Code follows project patterns?
  [ ] Breaks any CLAUDE.md rules?
  [ ] All related files updated?
  [ ] Could break tests?
  [ ] Security issues?
  [ ] Comments/clarity sufficient?
  [ ] Code maps need refresh?

After Merge

  merged PR automatically deletes branch on GitHub
  Pull main locally:
    git checkout main
    git pull origin main
  Check that code arrived:
    git log -1
    (Should show your commit)

HANDLING CONFLICTS
==================

If your branch diverges from main:

1. Check status
  git log main..HEAD        See commits unique to your branch
  git diff main...HEAD      See differences

2. Rebase instead of merge
  git rebase main
  (Replays your commits on top of main)

If conflicts occur during rebase:

  # Fix conflicted files
  # Edit files, resolve conflicts
  git add <file1> <file2>
  git rebase --continue     Resume rebase
  # Or abort:
  git rebase --abort        Go back to original state

3. Force-push only to YOUR branch
  git push origin feature/... --force-with-lease
  (--force-with-lease is safer than --force)

NEVER rebase main itself. Only rebase feature branches.

BRANCHING STRATEGY
==================

Main Branch (main)
  - Always stable
  - Always has passing tests
  - All code reviewed before merge
  - Direct commits forbidden

Feature Branches (feature/*, fix/*, refactor/*)
  - Branch from main
  - One feature/fix per branch
  - Work in progress OK here
  - Merge via PR after review

Branch Naming
  feature/add-xyz          New functionality
  fix/issue-xyz            Bug fixes
  refactor/simplify-xyz    Reorganization
  test/add-xyz-tests       New tests
  docs/update-readme       Documentation

Keep branch names short and descriptive.

INSPECTING & UNDOING
====================

View Commit History
  git log                   Full commit log
  git log --oneline -10     Last 10 commits (one line each)
  git log -p <file>         History of specific file with diffs

View Changes
  git status                What changed
  git diff                  Unstaged changes
  git diff --staged         Staged changes
  git diff main...HEAD      Diff from main to current branch

Undo Changes (SAFE - no force)

  Unstaged changes
    git restore <file>      Discard changes to file
    git restore .           Discard all changes

  Staged changes
    git restore --staged <file>
    git reset <file>        (Also works)

  Last commit (if unpushed)
    git reset --soft HEAD~1
    git commit --amend      Modify last commit
    (ONLY if not yet pushed)

Undo Pushed Changes (CREATE NEW COMMIT)

  NEVER use: git reset --hard (destroys work)
  INSTEAD:   git revert

  git revert <commit>       Creates new "undo" commit
  git push origin main      Push the undo

This is visible to others and safer than rewriting history.

EMERGENCY RECOVERY
==================

Accidentally Committed to Main?

  DON'T push yet!
  git reset --soft HEAD~1   Undo commit, keep changes staged
  git checkout -b feature/... Create feature branch
  git commit -m "..."       Re-commit to feature branch
  git push -u origin feature/...

Pushed Bad Code to Main?

  Create a revert commit:
    git revert <bad-commit-hash>
    git push origin main
  Then create a fix PR as normal.

Lost Commits?

  git reflog               Shows all recent operations
  git reset --hard <hash> Restore to specific point
  (Use reflog hash, not commit hash)

FILE PERMISSIONS
================

Executable Scripts

  After creating .sh or .bat script:
    git add <file>
    git update-index --chmod=+x <file>    (Make executable)
    git commit

  Don't chmod locally, tell git:
    chmod +x script.sh         (local)
    git update-index --chmod=+x script.sh (tell git)

Binary Files

  Add to .gitignore:
    *.pyc
    *.o
    *.dll

WORKING WITH SUBMODULES
=======================

CSC has submodules: irc/ and ops/

Cloning with Submodules
  git clone --recurse-submodules <repo-url>
  (Get submodule code too)

Updating Submodules
  cd irc                  Go into submodule
  git checkout main
  git pull origin main    Get latest
  cd ..
  git add irc             Tell main repo about new submodule version
  git commit -m "chore: Update irc submodule"

Don't forget to commit the submodule pointer update!

TIPS & TRICKS
=============

Amend Last Commit (unpushed only!)
  git commit --amend       Edit last commit message or add files
  git commit --amend --no-edit   Add files, keep message

Squash Commits Before PR
  git rebase -i HEAD~3     Squash last 3 commits
  (Interactive rebase, not for headless agents!)

Selective Staging
  git add -p               Interactive patch: stage lines, not whole files
  (Useful for separating unrelated changes)

View Commit Details
  git show <commit>        Show full commit with diff
  git show <commit>:<file> Show file at specific commit

Search History
  git log --grep="keyword" Search commit messages
  git log -S <string>      Search code changes (pickaxe)

See Who Changed What
  git blame <file>         Show committer of each line
  git blame -L10,20 <file> Blame lines 10-20

CONTINUOUS INTEGRATION
======================

GitHub Actions (if configured)

  Tests run automatically on every push
  If tests fail:
    Fix code
    Push again
    Tests re-run

PR Status Checks

  All checks must pass before merging:
    [ ] Build passes
    [ ] Tests pass
    [ ] Code review approved

COMMON MISTAKES
===============

Using git add -A
  ✗ git add -A              (Stages everything, including secrets!)
  ✓ git add <file1> <file2> (Specific files only)

Committing to Main Directly
  ✗ git commit -am "fix: ..." (While on main)
  ✓ git checkout -b fix/...   (New branch)
  ✓ git commit -m "fix: ..."

Forgetting refresh-maps
  ✗ Commit code without running refresh-maps
  ✓ refresh-maps before every commit

Writing vague messages
  ✗ "fixed bug"
  ✗ "WIP"
  ✓ "fix(server): handle missing channel in privmsg"

Including AI attribution
  ✗ "Claude: implemented feature X"
  ✓ "feat: implemented feature X"
  (AI work logged separately in contrib.txt)

Force-pushing to shared branches
  ✗ git push --force origin main   (NEVER!)
  ✓ git push origin feature/...    (OK on feature branches)

REFERENCE COMMANDS
==================

Setup & Config
  git init                 Initialize new repo
  git config user.name "X" Set name
  git config user.email "x@example.com"

Cloning & Updating
  git clone <url>          Clone repo
  git pull origin main     Fetch + merge latest
  git fetch origin         Just fetch (no merge)

Branching
  git branch               List branches
  git branch -d <name>    Delete branch
  git checkout -b <name>  Create + switch to branch
  git switch <name>        Switch to branch (newer syntax)

Committing
  git status               Show changes
  git diff                 Show unstaged changes
  git add <files>          Stage files
  git commit -m "msg"      Commit
  git push origin <branch> Push to remote

Reviewing
  git log --oneline -10    Last 10 commits
  git log -p <file>        File history with diffs
  git show <commit>        Show commit details

Undoing (safe)
  git restore <file>       Discard local changes
  git restore --staged     Unstage files
  git revert <commit>      Create undo commit

Inspecting
  git blame <file>         Who changed each line?
  git reflog               Show recent operations
  git fsck                 Check repository health

Final Thoughts
==============

Git is powerful but can be dangerous. When in doubt:

1. Don't force-push
2. Use branches, not main
3. Review before committing (git diff)
4. Run refresh-maps before commits
5. Create clear commit messages
6. Let reviewers approve PRs

The project is resilient because PRs require review. Use that safety net!
