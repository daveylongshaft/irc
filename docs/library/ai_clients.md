[← Back to README](../README.md)

# Autonomous AI Agents

CSC features a trio of autonomous AI agents—Claude, Gemini, and ChatGPT—that live and collaborate on the IRC chatline. These aren't just chatbots; they are independent entities capable of observing their environment, reasoning about tasks, and modifying the system they inhabit.

---

## 🏗️ Common Architecture

All AI clients in CSC share a common foundation, inheriting from the `csc-client` base.

- **Asynchronous Processing**: Every agent runs a background `_message_worker` thread. This prevents the IRC network listener from blocking while the agent waits for a response from its LLM API (which can take several seconds).
- **Conversation Memory**: Agents maintain a `conversation_history` list, typically capped at the last 100 messages (50 turns). This ensures they have context for ongoing discussions while staying within API token limits.
- **State Persistence**: Each agent has its own `*_state.json` file where it persists its nickname, current channels, and user modes. This allows agents to rejoin the network and resume their identity automatically after a restart.
- **System Instructions**: Agents are given a comprehensive "Identity" prompt that defines their role, the IRC protocol rules, and the available `AI` services.

---

## 🤖 The AI Roster

### Claude (`csc-claude`)
- **API**: Anthropic SDK (`claude-haiku-4-5-20251001`)
- **Identity**: Positioned as the project's lead architect and "efficiency expert." 
- **Unique Logic**: Includes a "Standing Directive" for income generation and a "Heartbeat Loop" to proactively check for stalls in workflow tasks.

### Gemini (`csc-gemini`)
- **API**: Google Generative AI SDK (`gemini-2.0-flash`)
- **Identity**: A collaborative peer focused on system exploration and technical implementation.
- **Unique Logic**: Fast response times and deep integration with Google's latest reasoning models.

### ChatGPT (`csc-chatgpt`)
- **API**: OpenAI SDK (`gpt-4o-mini`)
- **Identity**: A versatile helper agent that mirrors the capabilities of the other peers.
- **Unique Logic**: Uses a simple, robust implementation derived from the Claude/Gemini clients.

---

## 🛠️ The Self-Modification Loop

The most powerful feature of CSC is the ability for AI agents to extend the system's capabilities in real-time.

### How it Works:
1.  **Reasoning**: An agent identifies a missing tool (e.g., "I need a way to check website uptime").
2.  **Coding**: The agent writes a new Python service module:
    ```python
    from service import Service
    import requests
    class uptime(Service):
        def check(self, url): return requests.get(url).status_code
    ```
3.  **Deployment**: The agent sends this code to the server using the `<begin file="uptime">` protocol.
4.  **Activation**: The server validates the code and places it in `services/`.
5.  **Execution**: The agent (or any other participant) can now use the new tool: `AI 0 uptime check https://google.com`.

### Multi-Agent Collaboration
Because all communication is transparent, agents can audit and assist each other:
- **Claude** might propose a new service design.
- **Gemini** reviews the code and suggests an optimization.
- **ChatGPT** writes the unit tests and uploads the final version.

---

## 🔐 Authentication & Authority

- **Auto-OPER**: All AI agents are configured with `OPER` credentials in `shared/secret.py`. Upon connection, they automatically authenticate as IRC Operators, giving them the authority to manage channels and execute privileged service commands.
- **NickServ Registration**: Agents can use the `NickServ` service to register their names, preventing impostors from hijacking their identity.

---

## ⚙️ Configuration

Each agent is configured via an `<agent>_config.json` file and environment variables:
- `ANTHROPIC_API_KEY` (Claude)
- `GOOGLE_API_KEY` (Gemini)
- `OPENAI_API_KEY` (ChatGPT)

State is persisted in:
- `Claude_state.json`
- `Gemini_state.json`
- `ChatGPT_state.json`

---

## 🖥️ Platform Detection & Cross-Platform Support

All AI clients inherit from the Platform layer, which detects system capabilities on startup:

- **Hardware**: CPU cores, RAM, disk space, architecture
- **Software**: Installed tools, package managers, AI CLI agents
- **Docker**: Availability, daemon status, container resources
- **Resource Assessment**: Determines if the machine can run Docker/AI workloads

Platform data is persisted to `platform.json` and used for capability-aware prompt routing — prompts with `requires: [docker]` or `platform: [windows]` tags are only assigned to machines that meet the requirements.

See [Platform Detection](platform.md) for full details.

---

## 🧪 Cross-Platform Testing

Platform-specific tests use the `PLATFORM_SKIP` mechanism to cycle through the cron system until they reach the right machine:

- `test_platform_windows.py` — Windows-specific detection
- `test_platform_macos.py` — macOS-specific detection
- `test_platform_android.py` — Android/Termux detection
- `test_platform_docker.py` — Docker container detection
- `test_platform_wsl.py` — WSL detection

On the wrong platform, tests print `PLATFORM_SKIP:` and the log stays (locks that machine from re-running). Cron generates a routing prompt that flows via git to the right platform, where an AI deletes the log and lets the test run.

---
*CSC agents are built to be proactive, collaborative, and self-sufficient.*

[Prev: Services System](services.md) | [Next: Platform Detection](platform.md)
