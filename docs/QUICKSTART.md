# CSC Quickstart

How to run workorders, control agents, manage services, and batch AI tasks.

---

## Workorders (`wo`)

`wo` is a shortcut for `workorders`. All commands work with either name.

### Add a workorder

```bash
wo add "fix login bug" : Fix the null pointer on empty password in auth.py line 42.
```

Creates `wo/ready/PROMPT_fix_login_bug_<timestamp>.md`. The `:` separates the
short title from the full description. Use quotes around the title if it has spaces.

### List workorders

```bash
wo status                    # counts: ready / wip / done / hold
wo list ready                # list available workorders
wo list wip                  # list in-progress
wo list done                 # list completed
wo list                      # list all
```

### Read a workorder

```bash
wo read 1                    # read #1 from the ready list
wo read PROMPT_fix_login...  # or by full filename
```

### Move workorders

```bash
wo move 1 hold               # put on hold
wo move 1 done               # mark done (or agent does this automatically)
wo archive PROMPT_fix...     # move from done/ to archive/
wo delete PROMPT_fix...      # permanently delete
```

### Edit / append

```bash
wo edit PROMPT_fix... : Updated description here.
wo append PROMPT_fix... : Added note: also check logout path.
```

---

## Agents (`agent`)

### See what agents are available

```bash
agent list
```

Output shows available backends: `haiku`, `sonnet`, `opus`, `gemini-2.5-flash`, etc.

### Select and assign

```bash
agent select haiku           # set the active agent (faster, cheaper)
agent select sonnet          # for harder tasks

agent assign 1               # assign workorder #1 (from 'wo list ready') to selected agent
agent assign PROMPT_fix...   # or by filename
```

Shorthand: `wo assign 1 haiku` selects haiku and assigns #1 in one command.

### Watch it work

```bash
agent status                 # show running agent, WIP file, elapsed time
agent tail                   # tail last 20 lines of the WIP journal
agent tail 50                # tail last 50 lines
agent tail 50 PROMPT_fix...  # tail a specific WIP file
```

### Stop or kill

```bash
agent stop                   # graceful SIGTERM
agent kill                   # force kill, moves WIP back to ready/
```

---

## Services (`csc-ctl`)

`csc-ctl` controls everything except `csc-client`, `wo`, `agent`, and `sm-run`.

### Services

| Name | Description |
|------|-------------|
| `server` / `csc-server` | IRC server |
| `bridge` / `csc-bridge` | Protocol bridge |
| `claude` / `csc-claude` | Claude AI client |
| `gemini` / `csc-gemini` | Gemini AI client |
| `chatgpt` / `csc-chatgpt` | ChatGPT AI client |
| `queue-worker` / `qw` | Workorder queue daemon |
| `test-runner` / `tr` | Test automation daemon |
| `pm` | Process manager |
| `pr-review` | PR review agent |

Short aliases work: `csc-ctl start gemini` = `csc-ctl start csc-gemini`.

### Start / stop / restart

```bash
csc-ctl start gemini
csc-ctl stop gemini
csc-ctl restart gemini
csc-ctl restart gemini --force   # hard kill then start
csc-ctl start all                # start everything
csc-ctl stop all
```

### Install as persistent services

```bash
csc-ctl install all              # install all as system services
csc-ctl install queue-worker     # install one service
csc-ctl install --list           # preview what would be installed
```

**Linux**: creates systemd user units in `~/.config/systemd/user/csc-*.service`.
Managed with `systemctl --user start/stop/status csc-<name>`.

**Windows**: installs via NSSM (`bin/nssm.exe`) — proper Windows services, no terminal popups.
Managed with `net start/stop csc-<name>` or `csc-ctl start/stop`.

### Remove services

```bash
csc-ctl remove all
csc-ctl remove queue-worker
```

### Run a single cycle (one-shot)

```bash
csc-ctl cycle queue-worker       # process one batch of workorders now
csc-ctl cycle test-runner        # run one test cycle now
csc-ctl cycle pm                 # run PM assignment cycle
csc-ctl cycle pr-review          # run PR review agent once
```

### Config

```bash
csc-ctl status                   # show all service status
csc-ctl status queue-worker      # show one service status
csc-ctl show queue-worker        # show full config for a service
csc-ctl config queue-worker poll_interval 120   # set poll interval to 2min
csc-ctl enable gemini            # enable in config
csc-ctl disable gemini           # disable in config
csc-ctl dump > backup.json       # export all config
csc-ctl import < backup.json     # restore all config
```

---

## Batch AI Tasks

### Workorder batch (queue-worker)

The queue-worker picks up `wo/ready/PROMPT_*.md` files and assigns them to agents.
To process immediately without waiting for the next poll:

```bash
csc-ctl cycle queue-worker
```

To submit a batch and trigger it:

```bash
wo add "describe" : Full task description here.
csc-ctl cycle queue-worker
```

### Google Gemini Batch API (`gemini-batch`)

For large batches of AI work (many prompts processed asynchronously via the Batch API):

```bash
# Convert workorders to Gemini batch JSONL format
python bin/gemini-batch/gbatch_convert.py <workorder_dir> --out requests.jsonl

# Submit batch job
python bin/gemini-batch/gbatch_run.py submit requests.jsonl --model gemini-2.5-flash

# Check status
python bin/gemini-batch/gbatch_run.py status <job_name>

# Retrieve results when done
python bin/gemini-batch/gbatch_run.py retrieve <job_name> --out results.jsonl

# Or: convert + submit + poll + retrieve in one shot
python bin/gemini-batch/gbatch_run.py run batch_config.json --agent gemini
```

Requires `GOOGLE_API_KEY` in environment or `.env`.

The batch config JSON specifies which workorders, which model, and system context files:

```json
{
  "model": "gemini-2.5-flash",
  "workorder_dir": "wo/ready",
  "system_context": ["docs/README.1shot", "tools/INDEX.txt"]
}
```

Results come back as JSONL with one response per workorder. The executor
(`gbatch_executor.py`) can apply the results back to the filesystem.

---

## Typical Workflow

```bash
# 1. Add work
wo add "add dark mode to client" : Update the terminal client colors...

# 2. Start a cheap fast agent on it
agent select haiku
agent assign 1
agent status            # watch it pick up
agent tail              # follow the work log

# 3. If it's a big job, bump the agent
agent kill              # moves WIP back to ready
agent select sonnet
agent assign 1

# 4. Services always running? Check and install
csc-ctl status
csc-ctl install all

# 5. PR comes in? Review it
csc-ctl cycle pr-review
```
