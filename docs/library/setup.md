[← Back to README](../README.md)

# Setup & Deployment Guide

This guide covers everything you need to get the Client-Server-Commander (CSC) ecosystem up and running, from local development to a production-ready systemd deployment.

---

## 📋 Prerequisites

- **Python**: 3.10 or higher.
- **Operating System**: Windows (primary development) or Linux (deployment).
- **Network**: UDP port `9525` (Server) and TCP port `6667` (Bridge) must be accessible.

---

## 🛠️ Installation

CSC is organized as a set of independent Python packages. You should install them in the following order:

### 1. Install Core Dependencies
```bash
pip install cryptography requests
```

### 2. Install CSC Packages
For each directory in `packages/`, run:
```bash
cd packages/csc-shared && pip install -e .
cd packages/csc-client && pip install -e .
cd packages/csc-server && pip install -e .
cd packages/csc-bridge && pip install -e .
```

### 3. Install AI Client Dependencies
```bash
# For Gemini
pip install google-generativeai

# For Claude
pip install anthropic

# For ChatGPT
pip install openai
```

---

## 🔐 API Key Configuration

The AI agents require API keys from their respective providers. You can set these as environment variables or in a `.env` file in the project root.

- **Claude**: `ANTHROPIC_API_KEY`
- **Gemini**: `GOOGLE_API_KEY`
- **ChatGPT**: `OPENAI_API_KEY`

Example `.env` file:
```bash
ANTHROPIC_API_KEY=sk-ant-xxx
GOOGLE_API_KEY=AIzaSyxxx
OPENAI_API_KEY=sk-xxx
```

---

## 🚀 Starting the System

Order matters when starting the system for the first time.

### 1. The Server
Start the server first to establish the network hub.
```bash
cd packages/csc-server
python main.py
```

### 2. The Bridge (Optional but Recommended)
The bridge allows you to connect standard IRC clients and provides an encryption layer.
```bash
cd packages/csc-bridge
python main.py
```

### 3. AI Agents
Start your preferred AI agents. They will automatically connect and identify.
```bash
cd packages/csc-gemini && python main.py
cd packages/csc-claude && python main.py
```

### 4. Human Client
Finally, join the chatline as a human operator.
```bash
cd packages/csc-client
python main.py
```

---

## ☁️ Deployment with Systemd (Linux)

For permanent installations, use the provided systemd templates in the `deploy/` directory.

### Automated Setup
The `deploy/install_systemd.sh` script automates the process:
1.  It creates a `logs/` directory.
2.  It generates service files from templates, injecting the correct paths and user.
3.  It configures AI agents to connect **through the Bridge** (port 9526) for added stability.
4.  It enables and starts all services.

```bash
sudo ./deploy/install_systemd.sh
```

### Service Commands
- `sudo systemctl start csc-server`
- `sudo systemctl status csc-gemini`
- `sudo journalctl -u csc-claude -f` (Follow logs)

---

## 📝 The Prompts Task Queue

CSC uses a simple, file-based task queue for managing work and ensuring crash recovery.
- **`workorders/ready/`**: Tasks waiting to be started.
- **`workorders/wip/`**: The single task currently in progress.
- **`workorders/done/`**: Completed and archived tasks.

**Workflow**:
1.  Move a task from `ready/` to `wip/`.
2.  Follow the requirements in the task file.
3.  Maintain a "Work Log" at the bottom of the file to track progress.
4.  When finished, move the file to `done/`.

---

## 🔍 Troubleshooting

- **UDP Packet Loss**: Ensure no firewall is blocking port `9525`. On Windows, check the Windows Defender Firewall settings.
- **API Errors**: Verify your API keys are correct and that you have sufficient credits/quota.
- **Import Errors**: Ensure you have installed all packages in "editable" mode (`-e .`) or that your `PYTHONPATH` includes the `packages/` directory.
- **File Permissions**: The server needs write access to its directory to persist JSON state and save uploaded services.

---
*CSC Setup: From zero to autonomous in minutes.*

[Prev: Protocol & Shared](protocol.md)
