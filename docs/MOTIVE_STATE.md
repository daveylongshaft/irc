# Central Motive State

**Last Updated:** 2026-03-10
**Defined In:** docs/EVOLUTION.md
**Alignment Tracker:** logs/motive_state_progress.json

---

## The Core Statement

**"Autonomous, Cross-Platform, Self-Orchestrating Multi-AI System"**

### Four Pillars

#### 1. AUTONOMOUS
- **Definition:** Minimal human intervention in day-to-day operations
- **Key Characteristics:**
  - Self-detecting configuration problems
  - Self-healing when possible
  - Self-improving through feedback loops
  - Agents work independently
- **Current Autonomy Score:** 45
- **Target:** 95%+
- **Key Gap:** Services don't fully auto-start and self-heal yet
- **Next Step:** Implement self-healing infrastructure and auto-start for all services

#### 2. CROSS-PLATFORM
- **Definition:** Works identically on any system
- **Key Characteristics:**
  - No manual per-system configuration
  - Automatic adaptation to runtime environment
  - Seamless migration between platforms
  - Universal tooling and scripting
- **Current Cross-Platform Score:** 60
- **Target:** 100%
- **Key Gap:** Platform-specific paths and service management still need manual config
- **Next Step:** Extend platform detection layer to cover all deployment targets

#### 3. SELF-ORCHESTRATING
- **Definition:** Manages its own queue, priorities, and agent assignment
- **Key Characteristics:**
  - Intelligent workorder routing
  - Priority escalation/demotion
  - Load balancing across models
  - Feedback-driven optimization
- **Current Orchestration Score:** 35
- **Target:** 90%+
- **Key Gap:** PM model routing is basic; no feedback-driven optimization yet
- **Next Step:** Implement intelligent model routing in PM based on task complexity

#### 4. MULTI-AI
- **Definition:** Leverages all available models intelligently
- **Key Characteristics:**
  - Model selection by task complexity
  - Cost optimization through batching
  - Prompt caching for efficient reuse
  - Model-specific routing
- **Current Multi-AI Score:** 75
- **Target:** Maximize efficiency (40% of naive cost)
- **Key Gap:** Batch API and prompt caching not fully utilized
- **Next Step:** Implement batch API grouping and prompt caching across all agents

---

## Daily Alignment Questions

These are the questions we ask every day to check alignment:

1. **Autonomy**: Did we reduce manual intervention today? [Y/N]
2. **Cross-Platform**: Did we make something more portable today? [Y/N]
3. **Self-Orchestrating**: Did we improve system decision-making today? [Y/N]
4. **Multi-AI**: Did we improve cost/efficiency today? [Y/N]

---

## Metrics to Track Daily

See: `logs/motive_state_progress.json`

- Autonomy Score (0-100)
- Cross-Platform Score (0-100)
- Orchestration Score (0-100)
- Model Efficiency (% of naive cost)
- Days on aligned development
- Days since misalignment

---

## Decision Rubric

When unsure about a feature/task, use this rubric:

| Question | If YES → Do It | If No → Deprioritize |
|----------|---|---|
| Does this move us toward autonomy? | Prioritize | Reconsider |
| Does this improve cross-platform? | Prioritize | Reconsider |
| Does this enable self-orchestration? | Prioritize | Reconsider |
| Does this improve multi-AI efficiency? | Prioritize | Reconsider |

If any question is "yes", it's aligned. If all "no", it's distraction.

---

## The Next 90 Days

Focal areas to drive toward motive state:

### Week 1-2: Autonomy
- Implement self-healing for queue-worker and test-runner
- Add auto-restart with exponential backoff for crashed services

### Week 3-4: Cross-Platform
- Extend platform detection to cover macOS, Android, Docker environments
- Replace all hardcoded paths with platform-aware path resolution

### Week 5-8: Self-Orchestrating
- Implement feedback-driven model routing in PM
- Add priority escalation/demotion based on failure patterns

### Week 9-12: Multi-AI Efficiency
- Implement batch API grouping for similar tasks
- Add prompt caching across all agent interactions
