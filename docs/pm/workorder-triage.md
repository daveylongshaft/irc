# Workorder Triage Guide

## Classification System

Every workorder gets classified on two axes:
- **Urgency**: P0/P1/P2/P3 (see strategy.md)
- **Complexity**: simple / moderate / complex

### Complexity Heuristics

**Simple** (1 file, < 50 lines changed):
- Documentation updates (PROMPT_docs_*)
- Docstring additions (PROMPT_docstring*)
- Single test fixes where error is obvious
- Config changes, typo fixes

**Moderate** (2-5 files, requires understanding existing code):
- Test fixes that need code changes (PROMPT_fix_test_*)
- Bug fixes (PROMPT_fix_*)
- Feature additions to existing modules
- Refactoring within one package

**Complex** (5+ files, new patterns, cross-package):
- New package creation (csc-dmrbot, csc-scriptbot, csc-pm)
- Cross-system features (DCC, remote execution)
- Architecture changes (prompts→workorders rename)
- Infrastructure (test-runner, queue-worker upgrades)

## Current Workorder Inventory (as of session)

### P0 - Fix Now
| Workorder | Complexity | Assign To |
|-----------|-----------|-----------|
| PROMPT_fix_test_deliberate_fail | simple | DELETE (test was removed) |
| PROMPT_fix_test_server_irc | moderate | haiku |
| PROMPT_fix_test_storage_manager | moderate | haiku |
| PROMPT_fix_test_persistence | moderate | haiku |
| PROMPT_fix_test_integration | moderate | haiku |
| PROMPT_fix_test_nickserv | moderate | haiku |
| PROMPT_fix_test_topic_command | moderate | haiku |
| PROMPT_fix_test_botserv_logread | moderate | haiku |
| PROMPT_fix_test_botserv_logs | moderate | haiku |
| PROMPT_fix_test_builtin_service | moderate | haiku |
| PROMPT_fix_test_client_readline | moderate | haiku |
| PROMPT_fix_test_cryptserv_service | moderate | haiku |
| PROMPT_fix_test_coding_agent | moderate | sonnet |
| PROMPT_fix_dh_encryption | moderate | sonnet |
| PROMPT_fix_persistence_channel_modes | moderate | sonnet |
| PROMPT_fix_persistence_nickserv_mock | moderate | haiku |
| PROMPT_fix_platform_cli_flags | simple | haiku |

### P1 - Force Multipliers
| Workorder | Complexity | Assign To |
|-----------|-----------|-----------|
| PROMPT_project_manager_agent | complex | sonnet |
| PROMPT_script_runner_bot | complex | sonnet |
| docker-bot-client (dMrBot) | complex | sonnet |
| test-queue-worker-pipeline | moderate | haiku |
| PROMPT_create_sm_run_tool | moderate | haiku |

### P2 - Features
| Workorder | Complexity | Assign To |
|-----------|-----------|-----------|
| PROMPT_dcc_file_transfer | complex | sonnet |
| PROMPT_remote_service_execution | complex | sonnet |
| PROMPT_fifo_daemon_mode_for_csc_client | moderate | sonnet |
| PROMPT_ai_message_filtering_and_wakewords | moderate | haiku |
| enhance-platform-detection | moderate | haiku |
| PROMPT_test_agent_service | moderate | haiku |
| PROMPT_test_quit_cleanup | moderate | haiku |
| update-docs-queue-worker-system | moderate | haiku |

### P3 - Documentation (Free Models Only)
| Workorder | Complexity | Assign To |
|-----------|-----------|-----------|
| PROMPT_docs_svc_agent | simple | qwen/gemini-flash-lite |
| PROMPT_docs_svc_backup | simple | qwen/gemini-flash-lite |
| PROMPT_docs_svc_builtin | simple | qwen/gemini-flash-lite |
| PROMPT_docs_svc_cryptserv | simple | qwen/gemini-flash-lite |
| PROMPT_docs_svc_curl | simple | qwen/gemini-flash-lite |
| PROMPT_docs_svc_help | simple | qwen/gemini-flash-lite |
| PROMPT_docs_svc_module_manager | simple | qwen/gemini-flash-lite |
| PROMPT_docs_svc_nickserv | simple | qwen/gemini-flash-lite |
| PROMPT_docs_svc_ntfy | simple | qwen/gemini-flash-lite |
| PROMPT_docs_svc_patch | simple | qwen/gemini-flash-lite |
| PROMPT_docs_svc_version | simple | qwen/gemini-flash-lite |
| PROMPT_docstring_audit | simple | qwen/gemini-flash-lite |
| PROMPT_docstrings_01_packages | simple | qwen/gemini-flash-lite |
| PROMPT_docstrings_02_bridge | simple | qwen/gemini-flash-lite |
| PROMPT_docstrings_03_services_and_root | simple | qwen/gemini-flash-lite |
| PROMPT_docstrings_04_tests | simple | qwen/gemini-flash-lite |
| PROMPT_docstrings_05_regenerate_tools | simple | qwen/gemini-flash-lite |
| PROMPT_document_botserv_chanserv | simple | qwen/gemini-flash-lite |
| PROMPT_expand_client_programmatic_docs | simple | qwen/gemini-flash-lite |
| PROMPT_truth_table_conversions | simple | qwen/gemini-flash-lite |

## Auto-Triage Rules

The PM can classify workorders automatically based on patterns:

```
if filename starts with "PROMPT_fix_test_":
    urgency = P0, complexity = moderate, start_agent = haiku
if filename starts with "PROMPT_fix_":
    urgency = P0, complexity = moderate, start_agent = haiku
if filename starts with "PROMPT_docs_" or "PROMPT_docstring":
    urgency = P3, complexity = simple, start_agent = cheapest_available
if filename contains "urgent":
    urgency = P0
if description mentions "new package" or "create package":
    complexity = complex, start_agent = sonnet
if description mentions "refactor" or "rename" or "migrate":
    complexity = complex, start_agent = gemini-2.5-flash or sonnet
```

## Stale Workorder Detection

A workorder should be flagged if:
- It has 3+ PID entries in its work log (multiple failed attempts)
- It has been in ready/ for more than 7 days with no attempts
- It references files/functions that no longer exist in the codebase
