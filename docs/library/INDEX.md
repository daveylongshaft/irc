# Library Documentation Index

This index cross-references all active docs in `docs/library/` and links PM system docs in `docs/tools/pm/`.

## Table of Contents (all active library docs)

- [INDEX.md](INDEX.md)
- [AGENT_LAUNCHER_GUIDE.md](AGENT_LAUNCHER_GUIDE.md)
- [AGENT_SYSTEM.md](AGENT_SYSTEM.md)
- [AIDER.md](AIDER.md)
- [AUTONOMOUS_SYSTEM_ROADMAP.md](AUTONOMOUS_SYSTEM_ROADMAP.md)
- [BATCH_API_TOOL_USE.md](BATCH_API_TOOL_USE.md)
- [BRIDGE_SERVER_SETUP.md](BRIDGE_SERVER_SETUP.md)
- [CATALOG_AND_RANKING.md](CATALOG_AND_RANKING.md)
- [CLAUDE_API_STATUS.md](CLAUDE_API_STATUS.md)
- [CLEANUP_SUMMARY.md](CLEANUP_SUMMARY.md)
- [CLIENT_CONSOLE_GUIDE.md](CLIENT_CONSOLE_GUIDE.md)
- [CODE_FIXER_WORKFLOW.md](CODE_FIXER_WORKFLOW.md)
- [CONFIG_FILES_README.md](CONFIG_FILES_README.md)
- [CURRENT_ARCHITECTURE.md](CURRENT_ARCHITECTURE.md)
- [DEVCONTEXT.md](DEVCONTEXT.md)
- [DOCKER_AGENT_SETUP.md](DOCKER_AGENT_SETUP.md)
- [FEDERATION_ROADMAP.md](FEDERATION_ROADMAP.md)
- [FUTURE_VISION.md](FUTURE_VISION.md)
- [GENERIC_AGENTS.md](GENERIC_AGENTS.md)
- [MIRC_CONNECTION_SETUP.md](MIRC_CONNECTION_SETUP.md)
- [MOLTBOOK_SETUP.md](MOLTBOOK_SETUP.md)
- [NICKSERV_IMPLEMENTATION.md](NICKSERV_IMPLEMENTATION.md)
- [PATH_PROTECTION_BATCH_STRATEGY.md](PATH_PROTECTION_BATCH_STRATEGY.md)
- [PATH_PROTECTION_WORKORDER_TRACKING.md](PATH_PROTECTION_WORKORDER_TRACKING.md)
- [PM_RUNTIME_GAP_ANALYSIS.md](PM_RUNTIME_GAP_ANALYSIS.md)
- [PREFLIGHT_CHECKS.md](PREFLIGHT_CHECKS.md)
- [SCHEDULER_SETUP.md](SCHEDULER_SETUP.md)
- [SERVER_INFRASTRUCTURE_FIX.md](SERVER_INFRASTRUCTURE_FIX.md)
- [SERVICES_BOTSERV_CHANSERV.md](SERVICES_BOTSERV_CHANSERV.md)
- [SERVICE_SETUP.md](SERVICE_SETUP.md)
- [SERVICE_SYSTEM_RESTORATION.md](SERVICE_SYSTEM_RESTORATION.md)
- [SESSION_STATE.md](SESSION_STATE.md)
- [SHARED_FILE_AUDIT.md](SHARED_FILE_AUDIT.md)
- [SYSTEM_OVERVIEW.md](SYSTEM_OVERVIEW.md)
- [TASK_EXECUTION_MODES.md](TASK_EXECUTION_MODES.md)
- [TEST_BRIDGE.md](TEST_BRIDGE.md)
- [WORKER_QUICKSTART.md](WORKER_QUICKSTART.md)
- [WORKER_SYSTEM.md](WORKER_SYSTEM.md)
- [WORKORDERS_SERVICE_INTEGRATION.md](WORKORDERS_SERVICE_INTEGRATION.md)
- [ai_clients.md](ai_clients.md)
- [bridge.md](bridge.md)
- [client.md](client.md)
- [csc-ctl.md](csc-ctl.md)
- [platform.md](platform.md)
- [pr-review-merge-automation.md](pr-review-merge-automation.md)
- [protocol.md](protocol.md)
- [server.md](server.md)
- [services.md](services.md)
- [setup.md](setup.md)
- [translator-api.md](translator-api.md)
- [translator-cli.md](translator-cli.md)
- [translator-overview.md](translator-overview.md)

## Cross references

- **System operations:** [SYSTEM_OVERVIEW.md](SYSTEM_OVERVIEW.md), [CURRENT_ARCHITECTURE.md](CURRENT_ARCHITECTURE.md), [SERVICE_SETUP.md](SERVICE_SETUP.md), [SCHEDULER_SETUP.md](SCHEDULER_SETUP.md), [WORKER_SYSTEM.md](WORKER_SYSTEM.md).
- **Agents and workorders:** [AGENT_SYSTEM.md](AGENT_SYSTEM.md), [AGENT_LAUNCHER_GUIDE.md](AGENT_LAUNCHER_GUIDE.md), [WORKER_QUICKSTART.md](WORKER_QUICKSTART.md), [WORKORDERS_SERVICE_INTEGRATION.md](WORKORDERS_SERVICE_INTEGRATION.md), [TASK_EXECUTION_MODES.md](TASK_EXECUTION_MODES.md), [PM_RUNTIME_GAP_ANALYSIS.md](PM_RUNTIME_GAP_ANALYSIS.md).
- **PR automation:** [pr-review-merge-automation.md](pr-review-merge-automation.md), [PATH_PROTECTION_BATCH_STRATEGY.md](PATH_PROTECTION_BATCH_STRATEGY.md), [PATH_PROTECTION_WORKORDER_TRACKING.md](PATH_PROTECTION_WORKORDER_TRACKING.md).
- **Bridge/protocol/client/server stack:** [bridge.md](bridge.md), [protocol.md](protocol.md), [client.md](client.md), [server.md](server.md), [services.md](services.md), [platform.md](platform.md).
- **Translator docs:** [translator-overview.md](translator-overview.md), [translator-api.md](translator-api.md), [translator-cli.md](translator-cli.md).
- **PM docs (separate tree):** [`../tools/pm/README.md`](../tools/pm/README.md), [`../tools/pm/architecture.md`](../tools/pm/architecture.md), [`../tools/pm/system.md`](../tools/pm/system.md), [`../tools/pm/agents.md`](../tools/pm/agents.md), [`../tools/pm/workorder-triage.md`](../tools/pm/workorder-triage.md).

## Archived docs (no longer aligned with current code layout)

- [`../archive/library/PM_AGENT_MODULE_SUMMARY.md`](../archive/library/PM_AGENT_MODULE_SUMMARY.md) — references PM module functions (`find_batch_candidates`, `spawn_opus_self_fix`, `spawn_haiku_debug`, `run_cycle_safe`) that are not present in the current checked-in runtime scripts.
- [`../archive/library/AGENTS_ACTIVE_STATUS.md`](../archive/library/AGENTS_ACTIVE_STATUS.md) — point-in-time status doc tied to historical prompt paths/logs.

If you want these features reintroduced, implement them in the active PM runtime first, then promote updated docs back into `docs/library/`.
