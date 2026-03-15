# My Tool Pouch

Everything I can do from the command line. Exact syntax, every capability.

---

## csc-ctl — Service Management

Manage all CSC services. Source of truth for service state — always use this, never raw `systemctl` or `ps`.

| Command | Syntax | Example | What It Does |
|---------|--------|---------|--------------|
| status | `csc-ctl status` | `csc-ctl status` | Show all services (queue-worker, test-runner, pm, pr-reviewer, server, bridge, clients) |
| status (one) | `csc-ctl status <service>` | `csc-ctl status pm` | Show one service |
| show | `csc-ctl show <service>` | `csc-ctl show queue-worker` | Dump full JSON config for a service |
| show (setting) | `csc-ctl show <service> <setting>` | `csc-ctl show pm model` | Show one config value |
| config get | `csc-ctl config <service> <setting>` | `csc-ctl config pm model` | Get a config value |
| config set | `csc-ctl config <service> <setting> <value>` | `csc-ctl config pm model gemini-2.5-pro` | Set a config value |
| set | `csc-ctl set <key> <value>` | `csc-ctl set poll_interval 120` | Shorthand set on root config |
| enable | `csc-ctl enable <service>` | `csc-ctl enable gemini` | Enable a service |
| disable | `csc-ctl disable <service>` | `csc-ctl disable gemini` | Disable a service |
| restart | `csc-ctl restart <service>` | `csc-ctl restart pm` | Graceful restart (stop → wait → start) |
| restart force | `csc-ctl restart <service> --force` | `csc-ctl restart pm --force` | Hard kill then restart |
| restart all | `csc-ctl restart all` | `csc-ctl restart all` | Restart every service |
| cycle | `csc-ctl cycle <service>` | `csc-ctl cycle queue-worker` | Run one processing cycle manually |
| run | `csc-ctl run <service>` | `csc-ctl run pm` | Alias for cycle |
| install | `csc-ctl install` | `csc-ctl install` | Install all background services (cron/systemd) |
| install (one) | `csc-ctl install <service>` | `csc-ctl install queue-worker` | Install one service |
| install list | `csc-ctl install --list` | `csc-ctl install --list` | Show what would be installed |
| remove | `csc-ctl remove <service>` | `csc-ctl remove queue-worker` | Uninstall/stop a service |
| remove all | `csc-ctl remove all` | `csc-ctl remove all` | Remove all services |
| dump | `csc-ctl dump` | `csc-ctl dump` | Export full config to stdout (JSON) |
| dump (one) | `csc-ctl dump <service>` | `csc-ctl dump pm` | Export one service config |
| dump to file | `csc-ctl dump > backup.json` | `csc-ctl dump > backup.json` | Save full backup |
| import | `csc-ctl import < file.json` | `csc-ctl import < backup.json` | Restore config from JSON |
| import (one) | `csc-ctl import <service> < file` | `csc-ctl import pm < pm.json` | Restore one service |

**Known services:** `queue-worker`, `test-runner`, `pm`, `pr-reviewer`, `codex`, `server`, `bridge`, `gemini` (client)

---

## csc-ctl codex — Codex Cloud Tasks

Submit coding tasks to OpenAI Codex Cloud, monitor progress, and apply results. Uses your ChatGPT account (login via `npx codex login`).

| Command | Syntax | Example | What It Does |
|---------|--------|---------|--------------|
| submit | `csc-ctl codex submit <prompt\|wo>` | `csc-ctl codex submit improve_error_handling.md` | Submit a workorder or prompt to Codex Cloud |
| status | `csc-ctl codex status` | `csc-ctl codex status` | Show tracked tasks with live cloud status |
| list | `csc-ctl codex list` | `csc-ctl codex list -n 20` | List all Codex Cloud tasks (default: last 10) |
| apply | `csc-ctl codex apply <task_id>` | `csc-ctl codex apply e22f` | Apply diffs from a completed task locally |
| diff | `csc-ctl codex diff <task_id>` | `csc-ctl codex diff e22f` | Show the diff for a task |
| login | `csc-ctl codex login` | `csc-ctl codex login` | Check Codex authentication status |

**Setup:** `npm install -g @openai/codex && npx codex login`
**Config:** `csc-service.json` -> `codex.enabled`, `codex.environment`, `codex.max_concurrent_tasks`
**Tracking:** `tmp/codex_tasks.json` — maps task IDs to workorder filenames
**Auto-routing:** Workorders with `agent: codex` front-matter are auto-submitted by PM

---

## agent — AI Agent Execution

Select and run AI agents against workorders. Controls the queue-worker's active agent.

| Command | Syntax | Example | What It Does |
|---------|--------|---------|--------------|
| list | `agent list` | `agent list` | List available agent backends (haiku, sonnet, opus, gemini-*, qwen, etc.) |
| select | `agent select <name>` | `agent select sonnet` | Set active agent for next assign |
| assign | `agent assign <#\|filename>` | `agent assign 1` | Assign workorder #1 to selected agent and start it |
| assign (file) | `agent assign <filename>` | `agent assign my-task.md` | Assign by filename |
| status | `agent status` | `agent status` | Show running agent: PID, WIP file, elapsed time, last lines |
| tail | `agent tail` | `agent tail` | Show last 20 lines of WIP journal |
| tail N | `agent tail <N>` | `agent tail 50` | Show last N lines of WIP journal |
| tail file | `agent tail <N> <filename>` | `agent tail 30 my-task.md` | Tail specific WIP file |
| stop | `agent stop` | `agent stop` | Send SIGTERM — graceful stop |
| kill | `agent kill` | `agent kill` | Force kill + move WIP back to ready/ |
| help | `agent help` | `agent help` | Show help |

---

## wo — Workorder Queue Management

`wo` is an alias for `workorders`. Manages the prompt/task queue in `ops/wo/{ready,wip,done,hold,archive}/`.

| Command | Syntax | Example | What It Does |
|---------|--------|---------|--------------|
| status | `wo status` | `wo status` | Show queue counts: ready/wip/done/hold/archive |
| list | `wo list` | `wo list` | List workorders (default: ready) |
| list dir | `wo list <dir>` | `wo list wip` | List workorders in ready/wip/done/hold/archive |
| list all | `wo list all` | `wo list all` | List every workorder across all dirs |
| read | `wo read <#>` | `wo read 1` | Read workorder #1 from ready (first 20 lines) |
| read file | `wo read <filename>` | `wo read my-task.md` | Read by filename |
| add | `wo add "<desc>" : <content>` | `wo add "fix login bug" : Fix the null pointer in auth.py` | Create new workorder in ready/ |
| add (tags) | `wo add "<desc>" [tags] : <content>` | `wo add "fix login" codex : Fix auth.py` | Create with agent tag |
| edit | `wo edit <filename> : <content>` | `wo edit my-task.md : Updated instructions here` | Replace workorder content |
| append | `wo append <filename> : <text>` | `wo append my-task.md : Also fix the tests` | Append with timestamp |
| move | `wo move <#\|filename> <dir>` | `wo move 1 done` | Move between ready/wip/done/hold/archive |
| assign | `wo assign <#\|filename> <agent>` | `wo assign 1 sonnet` | Select agent + assign (same as agent select + agent assign) |
| hold | `wo hold <filename>` | `wo hold my-task.md` | Move to hold/ (pause) |
| archive | `wo archive <filename>` | `wo archive my-task.md` | Move done/ → archive/ after verification |
| delete | `wo delete <filename>` | `wo delete my-task.md` | Permanently delete |
| help | `wo help` | `wo help` | Show help |

**Dirs:** `ops/wo/ready/` → `ops/wo/wip/` → `ops/wo/done/` → `ops/wo/archive/`

---

## sm-run — Service Module Direct Execution

Run any CSC service class method directly from the command line without going through the IRC server.

> Note: service class lookup uses `services.<name>_service` module path relative to `csc_service/server/`.

| Command | Syntax | Example | What It Does |
|---------|--------|---------|--------------|
| run method | `sm-run <service_class> <method> [args...]` | `sm-run builtin list_dir .` | Call `<method>` on `<service_class>` with args |

**How it works:** Instantiates the `Service` base class and calls `handle_command(class, method, args, "CLI", addr)` — mirrors the `AI <token> <plugin> <method> [args]` IRC protocol but from shell.

---

## Quick Reference

```bash
# Check everything
csc-ctl status

# Run a workorder
wo list ready
agent select sonnet
agent assign 1

# Watch it work
agent tail 50
agent status

# Service config
csc-ctl show pm
csc-ctl config pm model gemini-2.5-pro-preview

# Restart a service
csc-ctl restart queue-worker

# Codex Cloud
csc-ctl codex submit improve_error_handling.md
csc-ctl codex status
csc-ctl codex list
csc-ctl codex apply <task_id>

# Direct service call (when fixed)
sm-run builtin ping
```
