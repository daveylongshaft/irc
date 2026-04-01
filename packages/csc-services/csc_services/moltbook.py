import json
import urllib.request
import urllib.parse
import urllib.error
from csc_services import Service


BASE_URL = "https://www.moltbook.com/api/v1"


class moltbook( Service ):
    """
    Moltbook social network service for AI agents.
    Provides posting, commenting, voting, feeds, and social features
    via the Moltbook API (www.moltbook.com).

    IRC usage:  AI <token> moltbook <command> [args...]
    CLI usage:  bin/moltbook <command> [args...]
    """

    def __init__(self, server_instance):
        super().__init__( server_instance )
        self.name = "moltbook"
        self.init_data()
        self.log( "Moltbook service initialized." )

    # ── HTTP helpers ──────────────────────────────────────────────────────────

    def _request(self, method, path, body=None, api_key=None):
        url = BASE_URL + path
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        data = json.dumps( body ).encode() if body is not None else None
        req = urllib.request.Request( url, data=data, headers=headers, method=method )

        try:
            with urllib.request.urlopen( req ) as resp:
                return json.loads( resp.read() )
        except urllib.error.HTTPError as e:
            body_bytes = e.read()
            try:
                err = json.loads( body_bytes )
            except Exception:
                err = {"error": body_bytes.decode( errors="replace" )}
            parts = [f"HTTP {e.code}: {err.get( 'error', 'Unknown error' )}"]
            if "hint" in err:
                parts.append( f"Hint: {err['hint']}" )
            if "retry_after_minutes" in err:
                parts.append( f"Retry after: {err['retry_after_minutes']} minutes" )
            if "retry_after_seconds" in err:
                parts.append( f"Retry after: {err['retry_after_seconds']} seconds" )
            if "daily_remaining" in err:
                parts.append( f"Daily remaining: {err['daily_remaining']}" )
            return {"error": " | ".join( parts )}
        except urllib.error.URLError as e:
            return {"error": f"Network error: {e.reason}"}

    def _get(self, path, params=None, api_key=None):
        if params:
            path += "?" + urllib.parse.urlencode(
                {k: v for k, v in params.items() if v is not None}
            )
        return self._request( "GET", path, api_key=api_key )

    def _post(self, path, body=None, api_key=None):
        return self._request( "POST", path, body=body, api_key=api_key )

    def _patch(self, path, body=None, api_key=None):
        return self._request( "PATCH", path, body=body, api_key=api_key )

    def _delete(self, path, body=None, api_key=None):
        return self._request( "DELETE", path, body=body, api_key=api_key )

    def _require_key(self):
        key = self.get_data( "api_key" )
        if not key:
            return None
        return key

    def _fmt(self, data):
        if isinstance( data, dict ) and "error" in data:
            return data["error"]
        return json.dumps( data, indent=2 )

    # ── Credential management ─────────────────────────────────────────────────

    def setup(self, *args):
        """Save API credentials. Usage: setup <api_key> <agent_name>"""
        if len( args ) < 2:
            return "Usage: moltbook setup <api_key> <agent_name>"
        api_key, agent_name = args[0], args[1]
        self.put_data( "api_key", api_key, flush=False )
        self.put_data( "agent_name", agent_name )
        return f"Credentials saved for agent '{agent_name}'."

    # ── Account ───────────────────────────────────────────────────────────────

    def register(self, *args):
        """Register a new agent. Usage: register <name> <description>"""
        if len( args ) < 2:
            return "Usage: moltbook register <name> <description>"
        name, description = args[0], " ".join( args[1:] )
        result = self._post( "/agents/register", {"name": name, "description": description} )
        if "error" in result:
            return self._fmt( result )
        agent = result.get( "agent", {} )
        api_key = agent.get( "api_key" )
        if api_key:
            self.put_data( "api_key", api_key, flush=False )
            self.put_data( "agent_name", name )
        lines = [
            "Registration successful!",
            f"  Agent name:        {name}",
            f"  API key:           {api_key}",
            f"  Claim URL:         {agent.get( 'claim_url', 'N/A' )}",
            f"  Verification code: {agent.get( 'verification_code', 'N/A' )}",
            "Your human must visit the claim URL to activate this agent.",
        ]
        return "\n".join( lines )

    def status(self, *args):
        """Check account/claim status. Usage: status"""
        key = self._require_key()
        if not key:
            return "No API key configured. Run: moltbook setup <api_key> <agent_name>"
        result = self._get( "/agents/status", api_key=key )
        if "error" in result:
            return self._fmt( result )
        status = result.get( "status", "unknown" )
        if status == "pending_claim":
            return f"Account status: {status} — your human must claim this agent account."
        elif status == "claimed":
            return f"Account status: {status} — account is active and ready."
        return f"Account status: {status}\n{self._fmt( result )}"

    # ── Posts ─────────────────────────────────────────────────────────────────

    def post(self, *args):
        """Create a text post. Usage: post <submolt> <title> <content...>"""
        if len( args ) < 3:
            return "Usage: moltbook post <submolt> <title> <content...>"
        key = self._require_key()
        if not key:
            return "No API key configured. Run: moltbook setup <api_key> <agent_name>"
        submolt, title = args[0], args[1]
        content = " ".join( args[2:] )
        result = self._post( "/posts", {
            "submolt": submolt, "title": title, "content": content
        }, api_key=key )
        if "error" in result:
            return self._fmt( result )
        p = result.get( "post", result.get( "data", {} ) )
        return f"Post created: ID={p.get( 'id', '?' )}"

    def post_link(self, *args):
        """Create a link post. Usage: post_link <submolt> <title> <url>"""
        if len( args ) < 3:
            return "Usage: moltbook post_link <submolt> <title> <url>"
        key = self._require_key()
        if not key:
            return "No API key configured. Run: moltbook setup <api_key> <agent_name>"
        result = self._post( "/posts", {
            "submolt": args[0], "title": args[1], "url": args[2]
        }, api_key=key )
        if "error" in result:
            return self._fmt( result )
        p = result.get( "post", result.get( "data", {} ) )
        return f"Link post created: ID={p.get( 'id', '?' )}"

    def comment(self, *args):
        """Comment on a post. Usage: comment <post_id> <content...>"""
        if len( args ) < 2:
            return "Usage: moltbook comment <post_id> <content...>"
        key = self._require_key()
        if not key:
            return "No API key configured. Run: moltbook setup <api_key> <agent_name>"
        post_id = args[0]
        content = " ".join( args[1:] )
        result = self._post( f"/posts/{post_id}/comments", {"content": content}, api_key=key )
        if "error" in result:
            return self._fmt( result )
        c = result.get( "comment", result.get( "data", {} ) )
        return f"Comment created: ID={c.get( 'id', '?' )}"

    def reply(self, *args):
        """Reply to a comment. Usage: reply <post_id> <parent_comment_id> <content...>"""
        if len( args ) < 3:
            return "Usage: moltbook reply <post_id> <parent_comment_id> <content...>"
        key = self._require_key()
        if not key:
            return "No API key configured. Run: moltbook setup <api_key> <agent_name>"
        post_id, parent_id = args[0], args[1]
        content = " ".join( args[2:] )
        result = self._post( f"/posts/{post_id}/comments", {
            "content": content, "parent_id": parent_id
        }, api_key=key )
        if "error" in result:
            return self._fmt( result )
        c = result.get( "comment", result.get( "data", {} ) )
        return f"Reply created: ID={c.get( 'id', '?' )}"

    def upvote(self, *args):
        """Upvote a post. Usage: upvote <post_id>"""
        if len( args ) < 1:
            return "Usage: moltbook upvote <post_id>"
        key = self._require_key()
        if not key:
            return "No API key configured. Run: moltbook setup <api_key> <agent_name>"
        result = self._post( f"/posts/{args[0]}/upvote", api_key=key )
        if "error" in result:
            return self._fmt( result )
        return f"Upvoted post {args[0]}"

    def downvote(self, *args):
        """Downvote a post. Usage: downvote <post_id>"""
        if len( args ) < 1:
            return "Usage: moltbook downvote <post_id>"
        key = self._require_key()
        if not key:
            return "No API key configured. Run: moltbook setup <api_key> <agent_name>"
        result = self._post( f"/posts/{args[0]}/downvote", api_key=key )
        if "error" in result:
            return self._fmt( result )
        return f"Downvoted post {args[0]}"

    def delete_post(self, *args):
        """Delete a post. Usage: delete_post <post_id>"""
        if len( args ) < 1:
            return "Usage: moltbook delete_post <post_id>"
        key = self._require_key()
        if not key:
            return "No API key configured. Run: moltbook setup <api_key> <agent_name>"
        result = self._delete( f"/posts/{args[0]}", api_key=key )
        if "error" in result:
            return self._fmt( result )
        return f"Deleted post {args[0]}"

    # ── Feeds ─────────────────────────────────────────────────────────────────

    def feed(self, *args):
        """Read the feed. Usage: feed [sort] [limit]"""
        key = self._require_key()
        if not key:
            return "No API key configured. Run: moltbook setup <api_key> <agent_name>"
        sort = args[0] if len( args ) > 0 else "hot"
        limit = args[1] if len( args ) > 1 else "10"
        result = self._get( "/feed", {"sort": sort, "limit": limit}, api_key=key )
        if "error" in result:
            return self._fmt( result )
        posts = result.get( "posts", result.get( "data", [] ) )
        lines = [f"Feed ({sort}, limit={limit}):"]
        for p in posts:
            lines.append(
                f"  [{p.get( 'id' )}] {p.get( 'title' )} | m/{p.get( 'submolt' )} "
                f"| by {p.get( 'author' )} | score={p.get( 'score', 0 )}"
            )
        return "\n".join( lines )

    def submolt_feed(self, *args):
        """Feed for a specific submolt. Usage: submolt_feed <submolt> [sort] [limit]"""
        if len( args ) < 1:
            return "Usage: moltbook submolt_feed <submolt> [sort] [limit]"
        key = self._require_key()
        if not key:
            return "No API key configured. Run: moltbook setup <api_key> <agent_name>"
        submolt = args[0]
        sort = args[1] if len( args ) > 1 else "new"
        limit = args[2] if len( args ) > 2 else "10"
        result = self._get( f"/submolts/{submolt}/feed", {"sort": sort, "limit": limit}, api_key=key )
        if "error" in result:
            return self._fmt( result )
        posts = result.get( "posts", result.get( "data", [] ) )
        lines = [f"m/{submolt} feed ({sort}):"]
        for p in posts:
            lines.append(
                f"  [{p.get( 'id' )}] {p.get( 'title' )} "
                f"| by {p.get( 'author' )} | score={p.get( 'score', 0 )}"
            )
        return "\n".join( lines )

    def get_post(self, *args):
        """Get a single post. Usage: get_post <post_id>"""
        if len( args ) < 1:
            return "Usage: moltbook get_post <post_id>"
        key = self._require_key()
        if not key:
            return "No API key configured. Run: moltbook setup <api_key> <agent_name>"
        result = self._get( f"/posts/{args[0]}", api_key=key )
        if "error" in result:
            return self._fmt( result )
        return self._fmt( result )

    def get_comments(self, *args):
        """Get comments on a post. Usage: get_comments <post_id> [sort]"""
        if len( args ) < 1:
            return "Usage: moltbook get_comments <post_id> [sort]"
        key = self._require_key()
        if not key:
            return "No API key configured. Run: moltbook setup <api_key> <agent_name>"
        sort = args[1] if len( args ) > 1 else "top"
        result = self._get( f"/posts/{args[0]}/comments", {"sort": sort}, api_key=key )
        if "error" in result:
            return self._fmt( result )
        comments = result.get( "comments", result.get( "data", [] ) )
        lines = [f"Comments on post {args[0]} ({sort}):"]
        for c in comments:
            lines.append(
                f"  [{c.get( 'id' )}] {c.get( 'author' )}: "
                f"{str( c.get( 'content', '' ) )[:80]}"
            )
        return "\n".join( lines )

    def search(self, *args):
        """Search posts. Usage: search <query> [limit]"""
        if len( args ) < 1:
            return "Usage: moltbook search <query> [limit]"
        key = self._require_key()
        if not key:
            return "No API key configured. Run: moltbook setup <api_key> <agent_name>"
        query = args[0]
        limit = args[1] if len( args ) > 1 else "10"
        result = self._get( "/posts/search", {"q": query, "limit": limit}, api_key=key )
        if "error" in result:
            return self._fmt( result )
        posts = result.get( "posts", result.get( "data", [] ) )
        lines = [f"Search results for '{query}':"]
        for p in posts:
            lines.append(
                f"  [{p.get( 'id' )}] {p.get( 'title' )} | m/{p.get( 'submolt' )} "
                f"| by {p.get( 'author' )} | score={p.get( 'score', 0 )}"
            )
        return "\n".join( lines )

    # ── Communities ───────────────────────────────────────────────────────────

    def create_submolt(self, *args):
        """Create a submolt community. Usage: create_submolt <name> <description>"""
        if len( args ) < 2:
            return "Usage: moltbook create_submolt <name> <description>"
        key = self._require_key()
        if not key:
            return "No API key configured. Run: moltbook setup <api_key> <agent_name>"
        name = args[0]
        description = " ".join( args[1:] )
        result = self._post( "/submolts", {"name": name, "description": description}, api_key=key )
        if "error" in result:
            return self._fmt( result )
        return f"Submolt created: https://www.moltbook.com/m/{name}"

    def subscribe(self, *args):
        """Subscribe to a submolt. Usage: subscribe <submolt>"""
        if len( args ) < 1:
            return "Usage: moltbook subscribe <submolt>"
        key = self._require_key()
        if not key:
            return "No API key configured. Run: moltbook setup <api_key> <agent_name>"
        result = self._post( f"/submolts/{args[0]}/subscribe", api_key=key )
        if "error" in result:
            return self._fmt( result )
        return f"Subscribed to m/{args[0]}"

    def unsubscribe(self, *args):
        """Unsubscribe from a submolt. Usage: unsubscribe <submolt>"""
        if len( args ) < 1:
            return "Usage: moltbook unsubscribe <submolt>"
        key = self._require_key()
        if not key:
            return "No API key configured. Run: moltbook setup <api_key> <agent_name>"
        result = self._delete( f"/submolts/{args[0]}/subscribe", api_key=key )
        if "error" in result:
            return self._fmt( result )
        return f"Unsubscribed from m/{args[0]}"

    def list_submolts(self, *args):
        """List all submolts. Usage: list_submolts [sort] [limit]"""
        key = self._require_key()
        if not key:
            return "No API key configured. Run: moltbook setup <api_key> <agent_name>"
        sort = args[0] if len( args ) > 0 else "popular"
        limit = args[1] if len( args ) > 1 else "20"
        result = self._get( "/submolts", {"sort": sort, "limit": limit}, api_key=key )
        if "error" in result:
            return self._fmt( result )
        submolts = result.get( "submolts", result.get( "data", [] ) )
        lines = [f"Submolts ({sort}):"]
        for s in submolts:
            lines.append(
                f"  m/{s.get( 'name' )} — {s.get( 'description', '' )} "
                f"| members={s.get( 'member_count', 0 )}"
            )
        return "\n".join( lines )

    # ── Social ────────────────────────────────────────────────────────────────

    def follow(self, *args):
        """Follow another agent. Usage: follow <agent_name>"""
        if len( args ) < 1:
            return "Usage: moltbook follow <agent_name>"
        key = self._require_key()
        if not key:
            return "No API key configured. Run: moltbook setup <api_key> <agent_name>"
        result = self._post( f"/agents/{args[0]}/follow", api_key=key )
        if "error" in result:
            return self._fmt( result )
        return f"Following {args[0]}"

    def unfollow(self, *args):
        """Unfollow an agent. Usage: unfollow <agent_name>"""
        if len( args ) < 1:
            return "Usage: moltbook unfollow <agent_name>"
        key = self._require_key()
        if not key:
            return "No API key configured. Run: moltbook setup <api_key> <agent_name>"
        result = self._delete( f"/agents/{args[0]}/follow", api_key=key )
        if "error" in result:
            return self._fmt( result )
        return f"Unfollowed {args[0]}"

    def profile(self, *args):
        """View profile. Usage: profile [agent_name]"""
        key = self._require_key()
        if not key:
            return "No API key configured. Run: moltbook setup <api_key> <agent_name>"
        if args:
            result = self._get( "/agents/profile", {"name": args[0]}, api_key=key )
        else:
            result = self._get( "/agents/me", api_key=key )
        if "error" in result:
            return self._fmt( result )
        agent = result.get( "agent", result.get( "data", {} ) )
        lines = [
            f"Name:      {agent.get( 'name' )}",
            f"Karma:     {agent.get( 'karma', 0 )}",
            f"Followers: {agent.get( 'follower_count', 0 )}",
            f"Following: {agent.get( 'following_count', 0 )}",
            f"Claimed:   {agent.get( 'is_claimed', False )}",
        ]
        return "\n".join( lines )

    def update_profile(self, *args):
        """Update profile description. Usage: update_profile <description>"""
        if len( args ) < 1:
            return "Usage: moltbook update_profile <description>"
        key = self._require_key()
        if not key:
            return "No API key configured. Run: moltbook setup <api_key> <agent_name>"
        description = " ".join( args )
        result = self._patch( "/agents/me", {"description": description}, api_key=key )
        if "error" in result:
            return self._fmt( result )
        return "Profile updated."

    # ── Notifications ─────────────────────────────────────────────────────────

    def notifications(self, *args):
        """View notifications. Usage: notifications [limit]"""
        key = self._require_key()
        if not key:
            return "No API key configured. Run: moltbook setup <api_key> <agent_name>"
        limit = args[0] if len( args ) > 0 else "10"
        result = self._get( "/agents/me/notifications", {"limit": limit}, api_key=key )
        if "error" in result:
            return self._fmt( result )
        notifs = result.get( "notifications", result.get( "data", [] ) )
        lines = [f"Notifications (latest {limit}):"]
        for n in notifs:
            lines.append( f"  [{n.get( 'type' )}] {n.get( 'message', str( n ) )}" )
        return "\n".join( lines )

    # ── Default / Help ────────────────────────────────────────────────────────

    def default(self, *args):
        """Show available commands."""
        return """Moltbook service — social network for AI agents.

COMMANDS:
  setup <api_key> <agent_name>        Save API credentials
  register <name> <description>       Register new agent
  status                              Check account status
  post <submolt> <title> <content>    Create text post
  post_link <submolt> <title> <url>   Create link post
  comment <post_id> <content>         Comment on post
  reply <post_id> <parent_id> <text>  Reply to comment
  upvote <post_id>                    Upvote a post
  downvote <post_id>                  Downvote a post
  feed [sort] [limit]                 Read feed
  submolt_feed <submolt> [sort] [lim] Feed for submolt
  get_post <post_id>                  Get single post
  get_comments <post_id> [sort]       Get comments
  delete_post <post_id>               Delete a post
  search <query> [limit]              Search posts
  create_submolt <name> <description> Create community
  subscribe <submolt>                 Subscribe to submolt
  unsubscribe <submolt>               Unsubscribe
  follow <agent_name>                 Follow agent
  unfollow <agent_name>               Unfollow agent
  profile [agent_name]                View profile
  update_profile <description>        Update description
  notifications [limit]               View notifications
  list_submolts [sort] [limit]        List submolts

IRC:  AI <token> moltbook <command> [args...]
CLI:  bin/moltbook <command> [args...]"""
