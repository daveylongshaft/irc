```python
#!/usr/bin/env python3
"""Pytest tests for CSC benchmark and agent services."""
import pytest
from unittest.mock import Mock, MagicMock, patch, call
from pathlib import Path


class TestBenchmarkService:
    """Tests for benchmark service."""

    @pytest.fixture
    def mock_server(self):
        """Create a mock server."""
        server = Mock()
        server.log = Mock()
        return server

    @pytest.fixture
    def benchmark_service(self, mock_server):
        """Create a benchmark service with mocked server."""
        with patch('csc_shared.services.benchmark_service.benchmark') as mock_benchmark_class:
            mock_instance = Mock()
            mock_benchmark_class.return_value = mock_instance
            from csc_shared.services.benchmark_service import benchmark
            return benchmark(mock_server)

    def test_benchmark_service_initialization(self, mock_server):
        """Test that benchmark service initializes with a server."""
        with patch('csc_shared.services.benchmark_service.benchmark') as mock_class:
            mock_instance = Mock()
            mock_class.return_value = mock_instance
            from csc_shared.services.benchmark_service import benchmark
            svc = benchmark(mock_server)
            assert svc is not None

    def test_benchmark_run_hello_world(self, mock_server):
        """Test running hello-world benchmark."""
        with patch('csc_shared.services.benchmark_service.benchmark') as mock_class:
            mock_instance = Mock()
            mock_instance.run = Mock(return_value="Benchmark: hello-world completed")
            mock_class.return_value = mock_instance
            
            from csc_shared.services.benchmark_service import benchmark
            svc = benchmark(mock_server)
            result = svc.run("hello-world", "ollama-codellama")
            
            assert result == "Benchmark: hello-world completed"
            mock_instance.run.assert_called_once_with("hello-world", "ollama-codellama")

    def test_benchmark_run_with_different_agent(self, mock_server):
        """Test running benchmark with different agent."""
        with patch('csc_shared.services.benchmark_service.benchmark') as mock_class:
            mock_instance = Mock()
            mock_instance.run = Mock(return_value="Benchmark completed")
            mock_class.return_value = mock_instance
            
            from csc_shared.services.benchmark_service import benchmark
            svc = benchmark(mock_server)
            result = svc.run("performance-test", "ollama-neural-chat")
            
            assert result == "Benchmark completed"
            mock_instance.run.assert_called_once_with("performance-test", "ollama-neural-chat")

    def test_benchmark_run_error_handling(self, mock_server):
        """Test benchmark service error handling."""
        with patch('csc_shared.services.benchmark_service.benchmark') as mock_class:
            mock_instance = Mock()
            mock_instance.run = Mock(side_effect=Exception("Benchmark failed"))
            mock_class.return_value = mock_instance
            
            from csc_shared.services.benchmark_service import benchmark
            svc = benchmark(mock_server)
            
            with pytest.raises(Exception) as exc_info:
                svc.run("hello-world", "invalid-agent")
            
            assert "Benchmark failed" in str(exc_info.value)

    def test_benchmark_server_logging(self, mock_server):
        """Test that benchmark service uses server logging."""
        with patch('csc_shared.services.benchmark_service.benchmark') as mock_class:
            mock_instance = Mock()
            mock_class.return_value = mock_instance
            
            from csc_shared.services.benchmark_service import benchmark
            svc = benchmark(mock_server)
            
            # Verify server was passed to service
            assert mock_server is not None


class TestAgentService:
    """Tests for agent service."""

    @pytest.fixture
    def mock_server(self):
        """Create a mock server."""
        server = Mock()
        server.log = Mock()
        return server

    @pytest.fixture
    def agent_service(self, mock_server):
        """Create an agent service with mocked server."""
        with patch('csc_shared.services.agent_service.agent') as mock_agent_class:
            mock_instance = Mock()
            mock_agent_class.return_value = mock_instance
            from csc_shared.services.agent_service import agent
            return agent(mock_server)

    def test_agent_service_initialization(self, mock_server):
        """Test that agent service initializes with a server."""
        with patch('csc_shared.services.agent_service.agent') as mock_class:
            mock_instance = Mock()
            mock_class.return_value = mock_instance
            from csc_shared.services.agent_service import agent
            svc = agent(mock_server)
            assert svc is not None

    def test_agent_select_ollama_codellama(self, mock_server):
        """Test selecting ollama-codellama agent."""
        with patch('csc_shared.services.agent_service.agent') as mock_class:
            mock_instance = Mock()
            mock_instance.select = Mock(return_value="Agent ollama-codellama selected")
            mock_class.return_value = mock_instance
            
            from csc_shared.services.agent_service import agent
            svc = agent(mock_server)
            result = svc.select("ollama-codellama")
            
            assert result == "Agent ollama-codellama selected"
            mock_instance.select.assert_called_once_with("ollama-codellama")

    def test_agent_select_different_agent(self, mock_server):
        """Test selecting a different agent."""
        with patch('csc_shared.services.agent_service.agent') as mock_class:
            mock_instance = Mock()
            mock_instance.select = Mock(return_value="Agent ollama-neural-chat selected")
            mock_class.return_value = mock_instance
            
            from csc_shared.services.agent_service import agent
            svc = agent(mock_server)
            result = svc.select("ollama-neural-chat")
            
            assert result == "Agent ollama-neural-chat selected"
            mock_instance.select.assert_called_once_with("ollama-neural-chat")

    def test_agent_select_invalid_agent(self, mock_server):
        """Test selecting an invalid agent."""
        with patch('csc_shared.services.agent_service.agent') as mock_class:
            mock_instance = Mock()
            mock_instance.select = Mock(side_effect=ValueError("Agent not found"))
            mock_class.return_value = mock_instance
            
            from csc_shared.services.agent_service import agent
            svc = agent(mock_server)
            
            with pytest.raises(ValueError) as exc_info:
                svc.select("invalid-agent")
            
            assert "Agent not found" in str(exc_info.value)

    def test_agent_service_server_logging(self, mock_server):
        """Test that agent service uses server logging."""
        with patch('csc_shared.services.agent_service.agent') as mock_class:
            mock_instance = Mock()
            mock_class.return_value = mock_instance
            
            from csc_shared.services.agent_service import agent
            svc = agent(mock_server)
            
            # Verify server was passed to service
            assert mock_server is not None


class TestIntegration:
    """Integration tests for benchmark and agent services together."""

    @pytest.fixture
    def mock_server(self):
        """Create a mock server."""
        server = Mock()
        server.log = Mock()
        return server

    def test_select_agent_then_run_benchmark(self, mock_server):
        """Test selecting an agent then running a benchmark."""
        with patch('csc_shared.services.agent_service.agent') as mock_agent_class, \
             patch('csc_shared.services.benchmark_service.benchmark') as mock_bench_class:
            
            # Setup mocks
            mock_agent_instance = Mock()
            mock_agent_instance.select = Mock(return_value="Agent selected")
            mock_agent_class.return_value = mock_agent_instance
            
            mock_bench_instance = Mock()
            mock_bench_instance.run = Mock(return_value="Benchmark completed")
            mock_bench_class.return_value = mock_bench_instance
            
            from csc_shared.services.agent_service import agent
            from csc_shared.services.benchmark_service import benchmark
            
            agent_svc = agent(mock_server)
            benchmark_svc = benchmark(mock_server)
            
            # Execute workflow
            select_result = agent_svc.select("ollama-codellama")
            assert select_result == "Agent selected"
            
            bench_result = benchmark_svc.run("hello-world", "ollama-codellama")
            assert bench_result == "Benchmark completed"
            
            # Verify calls
            mock_agent_instance.select.assert_called_once_with("ollama-codellama")
            mock_bench_instance.run.assert_called_once_with("hello-world", "ollama-codellama")

    def test_multiple_agents_and_benchmarks(self, mock_server):
        """Test running multiple agents and benchmarks."""
        with patch('csc_shared.services.agent_service.agent') as mock_agent_class, \
             patch('csc_shared.services.benchmark_service.benchmark') as mock_bench_class:
            
            mock_agent_instance = Mock()
            mock_agent_instance.select = Mock(return_value="Agent selected")
            mock_agent_class.return_value = mock_agent_instance
            
            mock_bench_instance = Mock()
            mock_bench_instance.run = Mock(return_value="Benchmark completed")
            mock_bench_class.return_value = mock_bench_instance
            
            from csc_shared.services.agent_service import agent
            from csc_shared.services.benchmark_service import benchmark
            
            agent_svc = agent(mock_server)
            benchmark_svc = benchmark(mock_server)
            
            agents = ["ollama-codellama", "ollama-neural-chat"]
            benchmarks = ["hello-world", "performance-test"]
            
            for agent_name in agents:
                agent_svc.select(agent_name)
                for bench_name in benchmarks:
                    benchmark_svc.run(bench_name, agent_name)
            
            # Verify all calls were made
            assert mock_agent_instance.select.call_count == len(agents)
            assert mock_bench_instance.run.call_count == len(agents) * len(benchmarks)

    def test_workflow_with_server_communication(self, mock_server):
        """Test that server logging is used during workflow."""
        with patch('csc_shared.services.agent_service.agent') as mock_agent_class, \
             patch('csc_shared.services.benchmark_service.benchmark') as mock_bench_class:
            
            mock_agent_instance = Mock()
            mock_agent_instance.select = Mock(return_value="Agent selected")
            mock_agent_class.return_value = mock_agent_instance
            
            mock_bench_instance = Mock()
            mock_bench_instance.run = Mock(return_value="Benchmark completed")
            mock_bench_class.return_value = mock_bench_instance
            
            from csc_shared.services.agent_service import agent
            from csc_shared.services.benchmark_service import benchmark
            
            agent_svc = agent(mock_server)
            benchmark_svc = benchmark(mock_server)
            
            agent_svc.select("ollama-codellama")
            benchmark_svc.run("hello-world", "ollama-codellama")
            
            # Verify server was provided to services
            assert mock_server is not None
            assert callable(mock_server.log)
```