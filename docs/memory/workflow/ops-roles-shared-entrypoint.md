# ops/roles/_shared Entrypoint

- Slug: `ops-roles-shared-entrypoint`
- Category: `workflow`
- Status: `reference`
- Tags: context, roles, shared, workflow
- Related: davey-collaboration-preferences, temp-clone-git-workflow
- Created: 2026-04-06T18:01:23Z
- Updated: 2026-04-06T18:01:23Z

## Summary
Shared role guidance exists in the main CSC tree and should be discovered through indexes, not loaded into every session up front.

## Details
In the main CSC tree, ops/roles/_shared/ contains shared guidance such as project maps, test guidelines, git rules, and work log rules. Its existence should be discoverable from indexes and cross references, but agents should only read it when they need deeper shared operational detail. It should not be stuffed into every startup context by default.
