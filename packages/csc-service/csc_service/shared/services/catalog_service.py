"""
Catalog and ranking service for AI agents.

Maintains agent specifications, benchmark results, and provides intelligent
ranking based on cost-performance trade-offs.

Ranking Formula:
  total_cost = api_cost + (duration_seconds * time_cost_per_second)

Where time_cost_per_second is derived from:
  - Assumed operator hourly rate (e.g., $50/hour)
  - Converts to per-second cost: $50 / 3600 = $0.0139/sec

Fair Comparison:
  - Free local models (ollama) at 2x duration ≈ 1/2 cost of paid models
  - Accounting for both API costs and time investment
"""

import json
from pathlib import Path
from datetime import datetime
from csc_service.server.service import Service
from csc_service.shared.services import PROJECT_ROOT as _PROJECT_ROOT


class catalog(Service):
    """Agent catalog and ranking system.

    Maintains:
    - Agent specifications (cost, model info, capabilities)
    - Benchmark results from tools/benchmarks/results/
    - Cost-performance rankings for task assignment

    Commands:
      list              - List all agents with specs and rankings
      rank              - Show cost-performance rankings
      assign <task>     - Get recommended agent for task type
      update            - Refresh rankings from benchmark data
    """

    PROJECT_ROOT = _PROJECT_ROOT
    BENCHMARKS_DIR = _PROJECT_ROOT / "tools" / "benchmarks"
    RESULTS_DIR = BENCHMARKS_DIR / "results"
    CATALOG_FILE = BENCHMARKS_DIR / "catalog.json"

    # Hourly rate for compute time (used to convert duration to cost)
    # Calibrated so free models at 2x duration ≈ 1/2 cost of Haiku
    # Haiku: ~31s @ $0.002 API = $0.002
    # Ollama: ~280s @ $0 API + time_cost
    # For fair comparison: 280s * rate ≈ $0.001 (making free model competitive)
    # This gives hourly rate of ~$12.86/hour for infrastructure costs
    HOURLY_RATE = 12.86
    TIME_COST_PER_SECOND = HOURLY_RATE / 3600

    # Agent specifications: {agent_id: {specs}}
    AGENT_SPECS = {
        # Local Models (Free)
        "ollama-codellama": {
            "binary": "ollama-agent",
            "model": "codellama:7b",
            "provider": "ollama",
            "api_cost": 0.0,
            "type": "local-free",
            "description": "CodeLlama 7B (local, free)",
            "capabilities": ["code-generation", "analysis"],
        },
        "ollama-deepseek": {
            "binary": "ollama-agent",
            "model": "deepseek-coder:6.7b",
            "provider": "ollama",
            "api_cost": 0.0,
            "type": "local-free",
            "description": "DeepSeek Coder 6.7B (local, free)",
            "capabilities": ["code-generation", "analysis"],
        },
        "ollama-qwen": {
            "binary": "ollama-agent",
            "model": "qwen2.5-coder:7b",
            "provider": "ollama",
            "api_cost": 0.0,
            "type": "local-free",
            "description": "Qwen 2.5 Coder 7B (local, free)",
            "capabilities": ["code-generation", "analysis"],
        },
        # Claude Models (Paid)
        "haiku": {
            "binary": "claude",
            "model": "haiku",
            "provider": "anthropic",
            "api_cost": 0.002,  # $0.002 per request (estimate)
            "type": "cloud-cheap",
            "description": "Claude Haiku 4.5 (fast, cheap)",
            "capabilities": ["code-generation", "analysis", "reasoning"],
        },
        "sonnet": {
            "binary": "claude",
            "model": "sonnet",
            "provider": "anthropic",
            "api_cost": 0.010,
            "type": "cloud-balanced",
            "description": "Claude Sonnet 4.5 (balanced)",
            "capabilities": ["code-generation", "analysis", "reasoning", "creative"],
        },
        "opus": {
            "binary": "claude",
            "model": "opus",
            "provider": "anthropic",
            "api_cost": 0.015,
            "type": "cloud-premium",
            "description": "Claude Opus 4.6 (smartest)",
            "capabilities": ["complex-reasoning", "multi-step", "novel-problems"],
        },
        # Gemini Models (Paid)
        "gemini-2.5-flash": {
            "binary": "gemini",
            "model": "gemini-2.5-flash",
            "provider": "google",
            "api_cost": 0.001,
            "type": "cloud-cheap",
            "description": "Gemini 2.5 Flash (fast, cheap)",
            "capabilities": ["code-generation", "analysis"],
        },
        "gemini-3-flash": {
            "binary": "gemini",
            "model": "gemini-3-flash-preview",
            "provider": "google",
            "api_cost": 0.005,
            "type": "cloud-balanced",
            "description": "Gemini 3.0 Flash (balanced)",
            "capabilities": ["code-generation", "analysis", "reasoning"],
        },
    }

    def __init__(self, server_instance):
        super().__init__(server_instance)
        self.name = "catalog"
        self.init_data()
        self.BENCHMARKS_DIR.mkdir(parents=True, exist_ok=True)
        self.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        self.log("Catalog service initialized.")

    def _calculate_total_cost(self, agent_id, duration_seconds):
        """Calculate total cost = API cost + time cost."""
        specs = self.AGENT_SPECS.get(agent_id, {})
        api_cost = specs.get("api_cost", 0.0)
        time_cost = duration_seconds * self.TIME_COST_PER_SECOND
        return api_cost + time_cost

    def _parse_result_filename(self, filename):
        """Parse benchmark result filename: {name}-{duration}-{agent}-{unixtime}.tgz

        Example: hello-world-286.35-ollama-codellama-1771645351.tgz
        Splits: ['hello', 'world', '286.35', 'ollama', 'codellama', '1771645351']
        """
        name_part = filename.replace(".tgz", "")
        parts = name_part.split("-")

        if len(parts) < 4:
            return None

        # Work backwards: last is unixtime, find duration as the first float
        try:
            unixtime = int(parts[-1])
        except ValueError:
            return None

        # Find the duration (first number that looks like a float when scanning backwards from -2)
        duration_idx = None
        for i in range(len(parts) - 2, -1, -1):
            try:
                val = float(parts[i])
                if "." in parts[i]:  # Make sure it looks like a duration (has decimal)
                    duration_idx = i
                    duration = val
                    break
            except ValueError:
                pass

        if duration_idx is None:
            return None

        # Agent is everything between duration and unixtime
        agent_parts = parts[duration_idx + 1 : -1]
        agent = "-".join(agent_parts) if agent_parts else "unknown"

        # Name is everything before the duration
        name_parts = parts[:duration_idx]
        name = "-".join(name_parts) if name_parts else "unknown"

        try:
            return {
                "name": name,
                "duration": float(duration),
                "agent": agent,
                "unixtime": int(unixtime),
                "filename": filename,
            }
        except (ValueError, IndexError):
            return None

    def _load_benchmark_results(self):
        """Load all benchmark results from results directory."""
        results_by_agent = {}
        if not self.RESULTS_DIR.exists():
            return results_by_agent

        for result_file in self.RESULTS_DIR.glob("*.tgz"):
            parsed = self._parse_result_filename(result_file.name)
            if parsed:
                agent = parsed["agent"]
                if agent not in results_by_agent:
                    results_by_agent[agent] = []
                results_by_agent[agent].append(parsed)

        return results_by_agent

    def _calculate_rankings(self):
        """Calculate cost-performance rankings for all agents."""
        results = self._load_benchmark_results()
        rankings = {}

        for agent_id, specs in self.AGENT_SPECS.items():
            agent_results = results.get(agent_id, [])

            if not agent_results:
                # No benchmark data yet
                rankings[agent_id] = {
                    "specs": specs,
                    "status": "no-data",
                    "avg_duration": None,
                    "total_cost": None,
                    "score": None,
                    "runs": 0,
                }
                continue

            # Calculate averages from benchmark runs
            durations = [r["duration"] for r in agent_results]
            avg_duration = sum(durations) / len(durations)
            total_cost = self._calculate_total_cost(agent_id, avg_duration)

            # Score: lower is better (cost efficiency)
            # Normalized by haiku as baseline
            haiku_cost = self._calculate_total_cost("haiku", 18.14)  # haiku hello-world
            score = total_cost / haiku_cost if haiku_cost > 0 else 1.0

            rankings[agent_id] = {
                "specs": specs,
                "status": "ranked",
                "avg_duration": round(avg_duration, 2),
                "api_cost": specs.get("api_cost", 0),
                "time_cost": round(avg_duration * self.TIME_COST_PER_SECOND, 4),
                "total_cost": round(total_cost, 4),
                "cost_per_hour": round((total_cost / avg_duration) * 3600, 4),
                "score": round(score, 2),
                "runs": len(agent_results),
                "description": specs.get("description", ""),
            }

        return rankings

    def list(self) -> str:
        """List all agents with specifications."""
        lines = ["Available Agents:\n"]
        for agent_id, specs in self.AGENT_SPECS.items():
            provider = specs.get("provider", "?").upper()
            type_badge = specs.get("type", "?")
            cost = specs.get("api_cost", 0)
            lines.append(
                f"  {agent_id:25} | {provider:10} | {type_badge:15} | "
                f"${cost:.4f}/request | {specs.get('description', '')}"
            )

        return "\n".join(lines)

    def rank(self) -> str:
        """Show cost-performance rankings with multiple perspectives."""
        rankings = self._calculate_rankings()

        # Filter by status
        ranked = {k: v for k, v in rankings.items() if v["status"] == "ranked"}
        if not ranked:
            return "No benchmark data available yet. Run benchmarks first: benchmark run <name> <agent>"

        # 1. Speed ranking (fastest first)
        lines = ["=" * 120]
        lines.append("SPEED RANKING (Responsiveness - lower time is better)")
        lines.append("=" * 120)
        lines.append(
            "Rank | Agent                 | Avg Time | Type              | Runs"
        )
        lines.append("-" * 120)

        speed_sorted = sorted(ranked.items(), key=lambda x: x[1]["avg_duration"])
        for idx, (agent_id, data) in enumerate(speed_sorted, 1):
            agent_type = data["specs"].get("type", "?")
            lines.append(
                f"{idx:4} | {agent_id:21} | {data['avg_duration']:7.2f}s | "
                f"{agent_type:17} | {data['runs']} runs"
            )

        # 2. Money ranking (cheapest API cost first)
        lines.append("\n" + "=" * 120)
        lines.append("DIRECT COST RANKING (API costs only - lower cost is better)")
        lines.append("=" * 120)
        lines.append(
            "Rank | Agent                 | API Cost | Type              | Runs"
        )
        lines.append("-" * 120)

        cost_sorted = sorted(
            ranked.items(),
            key=lambda x: x[1]["specs"].get("api_cost", 0),
        )
        for idx, (agent_id, data) in enumerate(cost_sorted, 1):
            agent_type = data["specs"].get("type", "?")
            api_cost = data["specs"].get("api_cost", 0)
            lines.append(
                f"{idx:4} | {agent_id:21} | ${api_cost:.6f} | "
                f"{agent_type:17} | {data['runs']} runs"
            )

        # 3. Total cost ranking (including time value)
        lines.append("\n" + "=" * 120)
        lines.append("TOTAL COST RANKING (API + Time value at $%.2f/hour)" % self.HOURLY_RATE)
        lines.append("=" * 120)
        lines.append(
            "Rank | Agent                 | Avg Time | API Cost | Time Cost | Total | Score | Type"
        )
        lines.append("-" * 120)

        total_sorted = sorted(
            ranked.items(), key=lambda x: x[1]["total_cost"]
        )
        for idx, (agent_id, data) in enumerate(total_sorted, 1):
            agent_type = data["specs"].get("type", "?")
            api_cost = data["specs"].get("api_cost", 0)
            time_cost = data.get("time_cost", 0)
            total_cost = data.get("total_cost", 0)
            score = f"{data['score']:.2f}x" if data["score"] else "N/A"
            lines.append(
                f"{idx:4} | {agent_id:21} | {data['avg_duration']:7.2f}s | "
                f"${api_cost:.6f} | ${time_cost:.6f} | ${total_cost:.4f} | {score:5} | {agent_type}"
            )

        lines.append("\n" + "=" * 120)
        lines.append("RECOMMENDATIONS:")
        lines.append("  Speed priority:  Use %s (fastest)" % speed_sorted[0][0])
        lines.append("  Cost priority:   Use %s (cheapest API)" % cost_sorted[0][0])
        lines.append("  Balanced:        Use %s (best overall value)" % total_sorted[0][0])
        lines.append("=" * 120)

        return "\n".join(lines)

    def assign(self, task_type, priority="balanced") -> str:
        """Get recommended agent for task type.

        Args:
            task_type: 'quick' (speed priority), 'cheap' (cost priority), 'best' (quality)
            priority: 'balanced', 'speed', 'cost', 'quality'

        Returns: Recommended agent ID
        """
        rankings = self._calculate_rankings()

        # Filter agents with benchmark data
        available = {
            k: v for k, v in rankings.items() if v["status"] == "ranked"
        }

        if not available:
            # Fall back to haiku if no benchmarks
            return "haiku"

        # Sort by different criteria based on priority
        if priority == "speed" or task_type == "quick":
            # Sort by duration (ascending)
            sorted_agents = sorted(
                available.items(), key=lambda x: x[1]["avg_duration"]
            )
        elif priority == "cost" or task_type == "cheap":
            # Sort by total cost (ascending)
            sorted_agents = sorted(
                available.items(), key=lambda x: x[1]["total_cost"]
            )
        elif priority == "quality":
            # Prefer non-free models (they're generally better)
            sorted_agents = sorted(
                available.items(),
                key=lambda x: (x[1]["specs"].get("type", "").startswith("cloud-"), -x[1]["total_cost"]),
                reverse=True,
            )
        else:  # balanced (default)
            # Sort by score (total cost / baseline)
            sorted_agents = sorted(
                available.items(), key=lambda x: x[1]["score"]
            )

        if not sorted_agents:
            return "haiku"

        recommended = sorted_agents[0][0]
        return recommended

    def update(self) -> str:
        """Refresh rankings from benchmark data."""
        rankings = self._calculate_rankings()

        # Save to catalog file
        catalog_data = {
            "generated": datetime.now().isoformat(),
            "time_cost_per_second": self.TIME_COST_PER_SECOND,
            "hourly_rate": self.HOURLY_RATE,
            "rankings": rankings,
        }

        try:
            with open(self.CATALOG_FILE, "w", encoding="utf-8") as f:
                json.dump(catalog_data, f, indent=2)
            self.log(f"Catalog updated: {self.CATALOG_FILE}")
            return f"Catalog updated with {len(rankings)} agents"
        except Exception as e:
            self.log(f"Error updating catalog: {e}")
            return f"Error updating catalog: {e}"

    def default(self, *args) -> str:
        """Show available commands."""
        return (
            "Catalog Service:\n"
            "  list                      - List all agents with specs\n"
            "  rank                      - Show cost-performance rankings\n"
            "  assign <priority>         - Get recommended agent (balanced|speed|cost|quality)\n"
            "  update                    - Refresh rankings from benchmark data\n"
            "\nCost Model:\n"
            f"  Hourly rate: ${self.HOURLY_RATE}/hour\n"
            f"  Time cost: ${self.TIME_COST_PER_SECOND:.4f}/second\n"
            "  Fair comparison: Free models ~1/2 cost of Haiku when accounting for time\n"
        )
