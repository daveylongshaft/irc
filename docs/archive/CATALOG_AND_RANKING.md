# Catalog and Ranking System

## Overview

The catalog service provides intelligent agent assignment based on cost-performance analysis. It ranks agents across multiple dimensions and recommends the best choice for different priorities.

## Cost Model

**Total Cost Formula:**
```
total_cost = API_cost + (duration_seconds × hourly_rate / 3600)
```

**Current Settings:**
- Hourly compute rate: $12.86/hour (infrastructure, not operator salary)
- This makes time costs meaningful but not dominant
- Free local models compete fairly with paid cloud APIs

**Cost Breakdown:**
- **Direct Cost**: API charges per request
  - Ollama agents: $0.00 (free, local)
  - Haiku: $0.002/request
  - Sonnet: $0.010/request
  - Opus: $0.015/request

- **Time Cost**: Duration × hourly infrastructure rate
  - Represents server/compute resources
  - Makes slow models less competitive
  - Incentivizes efficiency

## Ranking Perspectives

The system provides three ranking views:

### 1. Speed Ranking (Responsiveness)
Fastest first - best for interactive/real-time tasks

**Current Leaders:**
1. Haiku: 31.48s
2. Opus: 38.14s
3. Sonnet: 46.18s
4. Ollama-codellama: 286.35s

### 2. Direct Cost Ranking (Budget)
Lowest API cost first - ignoring time

**Current Leaders:**
1. Ollama-codellama: $0.00 (free!)
2. Haiku: $0.002
3. Sonnet: $0.010
4. Opus: $0.015

### 3. Total Cost Ranking (Value)
Combined cost including time value

**Current Leaders:**
1. Haiku: $0.1145 total (best value)
2. Opus: $0.1512 total
3. Sonnet: $0.1750 total
4. Ollama-codellama: $1.0229 total (too slow currently)

## Intelligent Task Assignment

```bash
# Get recommendation for different priorities
catalog assign balanced    # Best overall value (default)
catalog assign speed       # Fastest response time
catalog assign cost        # Cheapest API cost
catalog assign quality     # Best reasoning capability
```

**Algorithm:**
- Balanced: Sort by total cost score
- Speed: Sort by duration (ascending)
- Cost: Sort by API cost (ascending)
- Quality: Prefer premium models with proven data

## Fair Comparison: Free vs Paid

**The Challenge:**
Local free models (ollama) may be slower due to:
- Running in Docker containers
- No GPU optimization
- First-time model loading
- Network latency

**Fair Pricing:**
At $12.86/hour compute rate:
- If Ollama is 2x slower than Haiku: ~$0.01 cost (competitive!)
- If Ollama is 9x slower than Haiku: ~$0.45 cost (not competitive)
- Adjusting hourly rate makes free models more/less attractive

**Current Status:**
- Need more benchmark data from ollama-deepseek and ollama-qwen
- Currently ollama-codellama appears slower than expected
- May need to optimize Docker/ollama setup or investigate benchmarks

## Commands

```bash
# List all agents with specs
catalog list

# Show all three ranking perspectives
catalog rank

# Get recommendation for specific priority
catalog assign speed    # Fastest
catalog assign cost     # Cheapest
catalog assign quality  # Best quality

# Refresh rankings from benchmark results
catalog update
```

## Benchmark Integration

Catalog automatically:
1. Scans `benchmarks/results/` for tarball files
2. Parses filenames: `{name}-{duration}-{agent}-{unixtime}.tgz`
3. Calculates averages and costs
4. Generates rankings

**Filename Format:**
```
hello-world-286.35-ollama-codellama-1771645351.tgz
           ^      ^                  ^
           |      |                  +-- Unix timestamp
           |      +-- Agent name (can have dashes)
           +-- Duration in seconds
```

**Result Location:**
```
benchmarks/
  ├── results/
  │   ├── hello-world-286.35-ollama-codellama-1771645351.tgz
  │   └── complex-fft-58.15-haiku-1771643737.tgz
  ├── prompts/
  │   ├── hello-world.md
  │   └── complex-fft.md
  └── catalog.json (generated)
```

## Next Steps

1. **More Benchmark Data**: Run more benchmarks on all agents
   - `benchmark run hello-world ollama-deepseek`
   - `benchmark run hello-world ollama-qwen`
   - `benchmark run complex-fft ollama-*` (for each agent)

2. **Optimize Local Models**:
   - Check ollama container performance
   - Consider GPU acceleration
   - Investigate why 286s for hello-world

3. **Fair Pricing**: Adjust hourly rate to make free models competitive
   - Current: $12.86/hour (makes free 15x more expensive due to slowness)
   - Target: Free models at ~1/2 cost of Haiku when reasonably fast

4. **Task-Specific Ranking**:
   - Add task types (code-generation, analysis, reasoning)
   - Tag agents by capability
   - Recommend based on task type

## Example Usage

```python
from csc_shared.services.catalog_service import catalog

cat = catalog(server)

# Get rankings
cat.rank()  # Show all three perspectives

# Intelligent assignment
agent = cat.assign("task", priority="balanced")  # Returns agent_id

# Update from new benchmark results
cat.update()
```

---

**System Status**: ✅ Operational
**Benchmark Data**: 4 results (Haiku + 1 Ollama)
**Agents Ranked**: 4/8 (need more ollama data)
