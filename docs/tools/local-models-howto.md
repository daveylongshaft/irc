# How-To: Running Local Models for Workorders

This guide explains how to use local AI models (running in Docker) to process workorders in the CSC ecosystem.

## Prerequisites

1. **Docker** installed and running.
2. **Local AI engine** (e.g., ollama, dMrBot) running and listening for API requests.
3. **Agent queue directory** created: `c:\csc\agents\MODEL_NAME\queue\work`.

## Running a Local Model

To run a task with a local model, follow these steps:

### 1. Prepare the Workorder
Move the workorder from `ready/` to `wip/`:
```powershell
Move-Item c:\csc\workorderseady\TASK.md c:\csc\workorders\wip
```

### 2. Setup the Orders File
Create or update `c:\csc\agents\MODEL_NAME\queue\work\orders.md` using the template from `c:\csc\agents	emplates\default.md`.

Ensure the `orders.md` file points to the specific workorder in `wip/`:
```markdown
## Your Task
Here is what you need to do (from c:\csc\workorders\wip\TASK.md):
...
```

### 3. Execute the Model
Run the model using the `docker model run` command, passing the `orders.md` file as context:

```bash
docker model run ai/qwen3-coder @c:\csc\agents\qwen3-coder\queue\work\orders.md
```

**Note**: The `@` symbol prefix tells the model runner to load the context from the specified file.

## Recommended Models

- **qwen3-coder:latest**: Excellent for code editing and project refactoring.
- **deepseek-coder**: Good for logical reasoning and test fixes.
- **codellama**: Solid general-purpose coding assistant.

## Guidelines

- **Always Journal**: Just like paid agents, local models must journal their steps to the `wip/` file before executing them.
- **Cost**: Local models run at zero API cost ($0.00). Use them for high-volume or low-complexity tasks like documentation (P3) or simple bug fixes.
- **Cleanup**: After the model completes, verify its work and move the workorder to `done/`.
