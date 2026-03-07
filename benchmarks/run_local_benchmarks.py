#!/usr/bin/env python3
"""Run benchmarks on local ollama agents."""
import sys
from pathlib import Path

# Add project to path
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / "packages"))

from csc_shared.services.benchmark_service import benchmark
from csc_shared.services.agent_service import agent

class DummyServer:
    def log(self, msg):
        print(f"[benchmark] {msg}")

def main():
    # Create services
    server = DummyServer()
    benchmark_svc = benchmark(server)
    agent_svc = agent(server)

    # Test benchmarks and agents
    benchmarks = ["hello-world", "complex-fft"]
    agents = ["ollama-codellama", "ollama-deepseek", "ollama-qwen"]

    print("Running comprehensive benchmark suite...")
    print(f"{len(benchmarks)} benchmarks × {len(agents)} agents = {len(benchmarks) * len(agents)} tests\n")

    for benchmark_name in benchmarks:
        for agent_name in agents:
            print(f">>> Benchmark: {benchmark_name} | Agent: {agent_name}")

            # Select agent
            select_result = agent_svc.select(agent_name)
            if "not" in select_result.lower():
                print(f"ERROR: Agent not available: {select_result}")
                continue

            # Run benchmark
            result = benchmark_svc.run(benchmark_name, agent_name)
            print(result)
            print()

    print("✓ All benchmarks complete!")

if __name__ == "__main__":
    main()
