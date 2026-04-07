# Jules Integration

The Project Manager (PM) can now assign workorders to Jules, an autonomous coding agent. This document outlines the assignment logic, workflow, and configuration.

## Jules as an Assignment Target

Jules is available as an assignment target alongside other agents like Sonnet, Opus, and Gemini. Workorders can be assigned to Jules manually or automatically by the PM.

```bash
# Assign workorder 1 to Jules
workorders assign 1 jules
```

## Automatic Assignment by the PM

The PM will automatically assign a workorder to Jules if the following conditions are met:

1.  **Jules is enabled** in `csc-service.json`.
2.  **Jules has available capacity**. The maximum number of concurrent sessions is configured in `csc-service.json`.
3.  **The workorder is suitable for Jules**. The PM checks the workorder content for keywords like `bug`, `fix`, `refactor`, `test`, `documentation`, `feature`, `implement`, and `debug`.

## Workflow

1.  **Assignment**: The PM assigns a suitable workorder to Jules. The workorder is moved to the `wip` directory.
2.  **Execution**: The Jules client creates a new session and submits the workorder. If `auto_approve_plans` is enabled, Jules will automatically approve the plan and start execution.
3.  **Monitoring**: The PM monitors the status of the Jules session.
4.  **Completion**:
    *   If the session completes successfully, the PM retrieves the results, which should include a pull request URL. The workorder is moved to the `done` directory.
    *   If the session fails, the workorder is moved back to the `ready` directory to be reassigned.

## Configuration

The Jules integration is configured in `csc-service.json`:

```json
{
  "jules": {
    "enabled": true,
    "api_key_path": "config/jules_api_key",
    "max_concurrent_sessions": 3,
    "auto_approve_plans": true,
    "github_repo": "daveylongshaft/csc",
    "github_branch": "main"
  }
}
```

*   `enabled`: Enable or disable the Jules integration.
*   `api_key_path`: Path to the file containing the Jules API key.
*   `max_concurrent_sessions`: The maximum number of Jules sessions that can run in parallel.
*   `auto_approve_plans`: If `true`, the PM will instruct Jules to automatically approve plans.
*   `github_repo`: The GitHub repository that Jules will work on.
*   `github_branch`: The branch that Jules will use.
