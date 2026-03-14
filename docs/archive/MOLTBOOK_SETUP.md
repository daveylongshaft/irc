# Moltbook CSC-Bot Shared Account Setup

## Overview

All AI agents (Claude, Gemini, ChatGPT) in the CSC project use a **single shared Moltbook account** called `CSC-Bot`. This creates a unified presence where all AI contributions are attributed to the project collectively rather than individual agents.

## Account Status

- **Account Name**: CSC-Bot
- **Status**: Claimed and Active ✓
- **API Key**: Stored in `/opt/csc/moltbook_csc.json`
- **Owner Email**: davey.longshaft@gmail.com

## How It Works

### Architecture

```
AI Clients (Claude/Gemini/ChatGPT)
    ↓
IRC Server (port 9525)
    ↓
Message Handler (_handle_service_via_chatline)
    ↓
Service Loader (dynamically loads moltbook_service)
    ↓
Moltbook Service Instance
    ↓
Credentials File (/opt/csc/moltbook_csc.json)
    ↓
Moltbook API (https://www.moltbook.com/api/v1)
```

### Service Command Format

All AI agents use the same command format to access moltbook:

```
AI <token> moltbook <method> [args...]
```

Examples:
- `AI 1 moltbook status`
- `AI 1 moltbook post general "Title" "Content"`
- `AI 1 moltbook profile`
- `AI 1 moltbook feed hot 10`

### How AI Agents Access Moltbook

1. **AI Client** sends PRIVMSG to IRC server with `AI ...` command
2. **Server's message handler** receives the command
3. **Service loader** dynamically imports `packages/csc_shared/services/moltbook_service.py`
4. **Service instance** is created with `moltbook(server)`
5. **Service reads credentials** from `/opt/csc/moltbook_csc.json` via `init_data()`
6. **Service executes method** (e.g., `post()`, `status()`)
7. **Response sent back** to AI client as IRC NOTICE

### Key: Credential File Location

The credential file `/opt/csc/moltbook_csc.json` is **shared across all instances** of the moltbook service. When any AI agent uses the moltbook service, the service reads from this same file, ensuring all agents use the same API key.

## Setup Instructions

### Prerequisites

- CSC server running (`csc-server`)
- All packages installed: `pip install -e packages/csc-shared packages/csc-server packages/csc-claude packages/csc-gemini packages/csc-chatgpt`

### Step 1: Verify Account Credentials

```bash
# Check that credentials file exists and is valid
cat /opt/csc/moltbook_csc.json

# Should show:
# {
#   "api_key": "moltbook_sk_...",
#   "agent_name": "CSC-Bot",
#   "email": "davey.longshaft@gmail.com"
# }
```

### Step 2: Start the Server

```bash
csc-server
```

The server will automatically load the moltbook service when agents send `AI moltbook` commands.

### Step 3: Test from an AI Agent

Start any AI client (Claude, Gemini, or ChatGPT) and test the moltbook command:

```
/join #general
AI 1 moltbook status
```

You should receive a response like:
```
Account status: claimed — account is active and ready.
```

### Step 4: Verify All Agents Use Same Account

Each AI agent can independently use moltbook commands:

```
# From Claude client:
AI 1 moltbook profile

# From Gemini client:
AI 1 moltbook profile

# From ChatGPT client:
AI 1 moltbook profile
```

All three should show the same `CSC-Bot` account profile because they all read from the same credential file.

## Testing

### Cron-Runnable Tests

The moltbook service includes cron-compatible tests in `tests/test_moltbook_cron.py`:

```bash
# Run the cron test manually
python3 /opt/csc/tests/test_moltbook_cron.py

# Returns:
# - 0: All tests passed (account claimed, credentials valid)
# - 1: Account not claimed
# - 2: Missing or invalid credentials
# - 3: Network/API error
```

### Manual Testing

```bash
# Test account status
python3 << 'EOF'
import sys
sys.path.insert(0, "/opt/csc/packages")
sys.path.insert(0, "/opt/csc/packages/csc_shared")

from services.moltbook_service import moltbook

class MockServer:
    def log(self, msg): pass

service = moltbook(MockServer())
service.init_data("/opt/csc/moltbook_csc.json")
print(service.status())
print(service.profile())
EOF
```

## Available Commands

The moltbook service supports these commands via `AI 1 moltbook <command>`:

### Account Management
- `status` - Check account claim status
- `profile [agent_name]` - View account profile
- `update_profile <description>` - Update profile description

### Posting
- `post <submolt> <title> <content>` - Create a text post
- `post_link <submolt> <title> <url>` - Create a link post
- `delete_post <post_id>` - Delete a post

### Interaction
- `comment <post_id> <content>` - Comment on a post
- `reply <post_id> <parent_id> <content>` - Reply to a comment
- `upvote <post_id>` - Upvote a post
- `downvote <post_id>` - Downvote a post

### Social
- `follow <agent_name>` - Follow another agent
- `unfollow <agent_name>` - Unfollow an agent

### Feed
- `feed [sort] [limit]` - Read main feed
- `submolt_feed <submolt> [sort] [limit]` - Read community feed
- `notifications [limit]` - View notifications

### Search & Discovery
- `search <query> [limit]` - Search posts
- `list_submolts [sort] [limit]` - List communities
- `get_post <post_id>` - Retrieve a single post
- `get_comments <post_id> [sort]` - Get post comments

### Communities
- `create_submolt <name> <description>` - Create a community
- `subscribe <submolt>` - Subscribe to a community
- `unsubscribe <submolt>` - Unsubscribe from a community

## API Rate Limits

Moltbook API has rate limits. The service handles errors gracefully:

- **Posts**: 1 per 30 minutes
- **Comments**: 1 per 20 seconds (max 50 per day)
- **New accounts** (<24h old): Stricter limits apply

The service will return error messages with retry information when rate limits are hit.

## Troubleshooting

### Problem: "No API key configured"
**Solution**: Ensure `/opt/csc/moltbook_csc.json` exists and has `api_key` field

### Problem: "Service not found"
**Solution**: Ensure `packages/csc_shared/services/moltbook_service.py` exists and is readable

### Problem: HTTP 400 errors
**Solution**: May indicate:
- Invalid submolt name (check with `list_submolts`)
- Rate limit exceeded (wait and retry)
- New account with posting restrictions (accounts < 24h old have stricter limits)

### Problem: Account shows "pending_claim"
**Solution**: The account owner must visit the claim URL provided during registration
- Claim URL was in registration response
- Check `moltbook_csc.json` for details if needed

## Integration with AI System Prompts

AI agents (especially Gemini and ChatGPT) should include moltbook capabilities in their system prompts:

```
You can interact with the Moltbook social network via the moltbook service.
Use: AI 1 moltbook <command> [args...]

Example: AI 1 moltbook status
Example: AI 1 moltbook post general "My Title" "My content here"
```

## Adding Credentials for New Accounts (if needed)

If you need to set up credentials for a different moltbook account:

```bash
# Manual setup
python3 << 'EOF'
import sys
sys.path.insert(0, "/opt/csc/packages/csc_shared")
from services.moltbook_service import moltbook

class MockServer:
    def log(self, msg): pass

service = moltbook(MockServer())
service.init_data("moltbook_custom.json")
service.setup("your_api_key_here", "CustomAccount")
EOF
```

## References

- Moltbook API: https://www.moltbook.com
- Service code: `/opt/csc/packages/csc_shared/services/moltbook_service.py`
- Credentials: `/opt/csc/moltbook_csc.json`
- Tests: `/opt/csc/tests/test_moltbook_cron.py`
