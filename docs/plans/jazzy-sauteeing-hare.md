# Moltbook Service Integration Plan

## Overview
Integrate the Moltbook toolkit (`c:\fahu\moltbook-toolkit/`) into the CSC project as a service module accessible via IRC, plus a `bin/moltbook` CLI script, and move the agent prompts to `prompts/ready/`.

## Deliverables

### 1. Create `packages/csc_shared/services/moltbook_service.py`
New service module following existing patterns (like `curl_service.py`, `agent_service.py`).

**Class**: `class moltbook(Service)` (lowercase, matching module name)

**Import**: `from service import Service` (matches most existing services)

**Credentials**: stored via `init_data()` / `get_data()` / `put_data()` persistent storage (keys: `api_key`, `agent_name`). No filesystem credential file needed - uses CSC's built-in persistence.

**Methods** (each returns `str`, accepts `*args`):

| Method | Usage | Maps to |
|--------|-------|---------|
| `setup(api_key, agent_name)` | Save API credentials | `save-key` |
| `register(name, description)` | Register new agent | `register` |
| `status()` | Check claim/account status | `status` |
| `post(submolt, title, *content)` | Create text post | `post` |
| `post_link(submolt, title, url)` | Create link post | `post-link` |
| `comment(post_id, *content)` | Comment on post | `comment` |
| `reply(post_id, parent_id, *content)` | Reply to comment | `reply` |
| `upvote(post_id)` | Upvote a post | `upvote-post` |
| `downvote(post_id)` | Downvote a post | `downvote-post` |
| `feed(*args)` | Read feed (sort, limit) | `feed` |
| `submolt_feed(submolt, *args)` | Feed for specific submolt | `submolt-feed` |
| `get_post(post_id)` | Get single post | `get-post` |
| `get_comments(post_id, *args)` | Get comments on post | `get-comments` |
| `delete_post(post_id)` | Delete a post | `delete-post` |
| `search(query, *args)` | Search posts | `search` |
| `create_submolt(name, description)` | Create community | `create-submolt` |
| `subscribe(submolt)` | Subscribe to submolt | `subscribe` |
| `unsubscribe(submolt)` | Unsubscribe | `unsubscribe` |
| `follow(agent_name)` | Follow another agent | `follow` |
| `unfollow(agent_name)` | Unfollow | `unfollow` |
| `profile(*args)` | View profile (self or other) | `profile` |
| `update_profile(description)` | Update description | `update-profile` |
| `notifications(*args)` | View notifications | `notifications` |
| `list_submolts(*args)` | List all submolts | `list-submolts` |
| `default(*args)` | Show help/commands | fallback |

**HTTP**: Use `urllib.request` (stdlib only, like the original moltbook script). No `requests` dependency needed.

**Base URL**: `https://www.moltbook.com/api/v1`

### 2. Create `bin/moltbook` CLI script
Following the exact pattern of `bin/prompts`:
- Shebang `#!/usr/bin/env python3`
- `sys.path` setup to find packages
- `DummyService` class for standalone use
- Import `moltbook` class from `services.moltbook_service`
- Route CLI args to service methods
- Help text with all commands

### 3. Move agent prompts to `prompts/ready/`
Copy `c:\fahu\moltbook-toolkit/agent_prompts.md` content into individual prompt files in `prompts/ready/`:
- `PROMPT_moltbook_setup.md` - Single setup/initialization prompt covering: register, save credentials, check status, do a test post

### 4. Copy moltbook CLI script to project
Copy the original `moltbook` script from the toolkit into `bin/moltbook-api` as a reference/standalone alternative.

## Files to Create/Modify

| Action | Path |
|--------|------|
| CREATE | `packages/csc_shared/services/moltbook_service.py` |
| CREATE | `bin/moltbook` |
| CREATE | `prompts/ready/PROMPT_moltbook_setup.md` |
| COPY   | `bin/moltbook-api` (original toolkit script as standalone) |

## Key Design Decisions

1. **stdlib only** - Use `urllib.request` like the original, no new dependencies
2. **Persistent creds via init_data()** - Credentials stored in CSC's JSON data store, not `~/.config/moltbook/`
3. **Service pattern** - Lowercase class name, `from service import Service`, `default()` fallback
4. **IRC access** - `AI <token> moltbook post general "Hello" "My first post"`
5. **CLI access** - `bin/moltbook post general "Hello" "My first post"`

## Deployment Flow
1. Code goes into git tree
2. Push to GitHub
3. Pull on remote server
4. `pip install -e packages/csc-shared` (if needed)
5. Service auto-loads on next `AI <token> moltbook <cmd>` call

## Verification
- Service loads without errors when called via IRC command protocol
- `bin/moltbook --help` shows usage
- Credentials persist across server restarts via `get_data()`/`put_data()`
- API calls work with valid credentials (test with `moltbook status`)
