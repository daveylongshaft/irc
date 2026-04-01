# Assignment History & Lessons Learned

## What Worked

### haiku + simple single-file tasks
- `implement_prompts_append_command` → COMPLETE (added append subcommand to workorders service)
- Good for: test fixes, single-file feature adds, config changes
- Fast, cheap, reliable within its capability range

### gemini-2.5-flash + multi-file refactoring
- `rename-prompts-to-workorders` → COMPLETE (after gemini-3-pro and flash-lite both failed)
- Can handle cross-file renames and path updates
- Good balance of capability and cost

## What Failed

### haiku + new package creation
- `docker-bot-client` (dMrBot) → INCOMPLETE x5
- Haiku created main.py with a huge docstring but no actual implementation
- Lesson: haiku cannot architect new packages. Don't assign new-package tasks to haiku.

### haiku + benchmark execution
- `benchmark-hello-world` → INCOMPLETE x6
- Multiple attempts, never completed
- Benchmarks require understanding the full pipeline, too complex for haiku

### local models (qwen) + anything non-trivial
- `qwen-fs-test` → INCOMPLETE
- Local 7B models struggle with CSC project structure
- OK for documentation, fail at code changes that require project understanding

### gemini-3-pro + refactoring
- `rename-prompts-to-workorders` → needed multiple restarts before flash took over
- Expensive and not more reliable than flash for this type of work

### gemini-2.5-flash-lite + refactoring
- `rename-prompts-to-workorders` → INCOMPLETE x3
- Too lightweight for multi-file changes
- Stick to documentation and trivial edits

### opus + complex feature work
- `urgent_fix_queue-worker_agent_exit_detection` → INCOMPLETE x3
- Even opus struggles with the queue-worker's complexity
- Human ended up doing this one interactively
- Lesson: some tasks need interactive human+AI collaboration, not autonomous agents

## Patterns

1. **Escalation works**: flash-lite failed → flash succeeded on the rename task
2. **Repeated failure = wrong agent**: 3+ INCOMPLETEs means escalate, don't retry
3. **New packages need sonnet minimum**: haiku can't create coherent multi-file packages
4. **Infrastructure tasks often need human guidance**: queue-worker, test-runner required interactive sessions
5. **Documentation is ideal for free models**: low risk, easy to verify, no API cost

## Test Health Snapshot

Passing: test_agent_service, test_botserv_logread, test_botserv_logs, test_builtin_service,
test_client_readline, test_cryptserv_service, test_curl_service, test_docker_clone_workflow,
test_file_upload_integration, test_file_upload_system, test_gateway_integration,
test_integration, test_irc_normalizer, test_moltbook_cron, test_moltbook_service,
test_nickserv, test_nickserv_service, test_ntfy_service, test_patch_service,
test_persistence, test_platform, test_prompt_capabilities, test_queue_utils,
test_s2s_federation, test_server_irc, test_shared_channel, test_topic_command,
test_user_modes, test_version_service, test_wip_journal

Failing: test_backup_service, test_botserv, test_chanserv, test_client_irc,
test_coding_agent, test_gemini_irc, test_help_service, test_module_manager_service,
test_prompts_service

Skipped (platform-gated): test_channel_mode_ban, test_claude_irc, test_platform_android,
test_platform_docker, test_platform_macos, test_platform_windows, test_platform_wsl,
test_server_console_irc, test_shared_irc, test_wakeword

Unknown/Empty: test_gemini, test_queue_worker, test_storage_manager, test_workorders_migration
