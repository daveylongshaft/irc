# Temp Clone Git Workflow

- Slug: `temp-clone-git-workflow`
- Category: `workflow`
- Status: `reference`
- Tags: git, temp-clone, workflow
- Related: davey-collaboration-preferences
- Created: 2026-04-06T17:51:18Z
- Updated: 2026-04-06T17:51:18Z

## Summary
Do implementation work in C:/csc/tmp/irc on a feature branch, open a PR, and keep the main checkout disposable.

## Details
A periodic script resets C:/csc, C:/csc/irc, and C:/fahu to origin/main. Implementation work should happen in C:/csc/tmp/irc. Use a feature branch there, push it, and create a PR back to main. Do not rely on the main checkout to retain unmerged changes.
