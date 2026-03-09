```python
"""Tests for Docker clone workflow (mock Docker — no Docker required)."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, call

from coding_agent.docker_runner import DockerRunner


class TestDockerRunnerCloneWorkflow:
    """Test DockerRunner's clone workflow with mocked subprocess."""

    def test_run_with_clone_git_fails(self):
        """If git clone fails, should return error."""
        runner = DockerRunner(timeout=30)

        mock_result = MagicMock()
        mock_result.returncode = 128
        mock_result.stderr = "fatal: repository not found"

        with patch("coding_agent.docker_runner.subprocess.run", return_value=mock_result):
            stdout, stderr, code = runner.run_with_clone(
                repo_url="https://github.com/nonexistent/repo.git",
                script="echo hello",
                runtime="bash",
            )
        assert code != 0
        assert "clone failed" in stderr.lower()

    @patch("coding_agent.docker_runner.subprocess.run")
    @patch("coding_agent.docker_runner.tempfile.mkdtemp")
    @patch("coding_agent.docker_runner.shutil.rmtree")
    def test_run_with_clone_success(self, mock_rmtree, mock_mkdtemp, mock_run):
        """Successful clone+run should return stdout."""
        tmp_dir = "/tmp/test-clone-dir"
        mock_mkdtemp.return_value = tmp_dir

        # First call: git clone (success)
        clone_result = MagicMock()
        clone_result.returncode = 0

        # Second call: docker run (success)
        docker_result = MagicMock()
        docker_result.returncode = 0
        docker_result.stdout = "output"
        docker_result.stderr = ""

        mock_run.side_effect = [clone_result, docker_result]

        with patch("coding_agent.docker_runner.os.path.exists", return_value=True):
            runner = DockerRunner(timeout=30)
            stdout, stderr, code = runner.run_with_clone(
                repo_url="https://github.com/test/repo.git",
                script="echo hello",
                runtime="bash",
            )

        assert code == 0
        assert stdout == "output"
        # Cleanup should be called
        mock_rmtree.assert_called_once_with(tmp_dir)

    @patch("coding_agent.docker_runner.subprocess.run")
    @patch("coding_agent.docker_runner.tempfile.mkdtemp")
    @patch("coding_agent.docker_runner.shutil.rmtree")
    def test_run_with_clone_cleanup_on_failure(self, mock_rmtree, mock_mkdtemp, mock_run):
        """Clone dir should be cleaned up even on Docker failure."""
        tmp_dir = "/tmp/test-clone-fail"
        mock_mkdtemp.return_value = tmp_dir

        clone_result = MagicMock()
        clone_result.returncode = 0

        docker_result = MagicMock()
        docker_result.returncode = 1
        docker_result.stdout = ""
        docker_result.stderr = "error"

        mock_run.side_effect = [clone_result, docker_result]

        with patch("coding_agent.docker_runner.os.path.exists", return_value=True):
            runner = DockerRunner(timeout=30)
            stdout, stderr, code = runner.run_with_clone(
                repo_url="https://github.com/test/repo.git",
                script="exit 1",
                runtime="bash",
            )

        assert code != 0
        mock_rmtree.assert_called_once_with(tmp_dir)


class TestCloneAndRunLifecycle:
    """Test the full clone_and_run lifecycle."""

    @patch("coding_agent.docker_runner.subprocess.run")
    @patch("coding_agent.docker_runner.tempfile.mkdtemp")
    @patch("coding_agent.docker_runner.shutil.rmtree")
    def test_full_lifecycle_with_push(self, mock_rmtree, mock_mkdtemp, mock_run):
        """Full lifecycle: clone -> run -> detect changes -> commit -> push -> cleanup."""
        tmp_dir = "/tmp/test-lifecycle"
        mock_mkdtemp.return_value = tmp_dir

        # Mock subprocess calls in order:
        # 1. git clone
        clone_result = MagicMock(returncode=0)
        # 2. docker run
        docker_result = MagicMock(returncode=0, stdout="done", stderr="")
        # 3. git status --porcelain (has changes)
        status_result = MagicMock(returncode=0, stdout="M file.py\n")
        # 4. git add -A
        add_result = MagicMock(returncode=0)
        # 5. git commit
        commit_result = MagicMock(returncode=0)
        # 6. git push
        push_result = MagicMock(returncode=0)

        mock_run.side_effect = [
            clone_result, docker_result, status_result,
            add_result, commit_result, push_result,
        ]

        with patch("coding_agent.docker_runner.os.path.exists", return_value=True):
            runner = DockerRunner(timeout=60)
            result = runner.clone_and_run(
                repo_url="https://github.com/test/repo.git",
                script="echo hello > file.py",
                runtime="bash",
                commit_msg="Test commit",
                push=True,
            )

        assert result["status"] == "SUCCESS"
        assert result["pushed"] is True
        assert result["exit_code"] == 0
        mock_rmtree.assert_called_once_with(tmp_dir)

    @patch("coding_agent.docker_runner.subprocess.run")
    @patch("coding_agent.docker_runner.tempfile.mkdtemp")
    @patch("coding_agent.docker_runner.shutil.rmtree")
    def test_lifecycle_no_changes(self, mock_rmtree, mock_mkdtemp, mock_run):
        """If no changes after run, should not push."""
        tmp_dir = "/tmp/test-no-changes"
        mock_mkdtemp.return_value = tmp_dir

        clone_result = MagicMock(returncode=0)
        docker_result = MagicMock(returncode=0, stdout="done", stderr="")
        # No changes
        status_result = MagicMock(returncode=0, stdout="")

        mock_run.side_effect = [clone_result, docker_result, status_result]

        with patch("coding_agent.docker_runner.os.path.exists", return_value=True):
            runner = DockerRunner(timeout=60)
            result = runner.clone_and_run(
                repo_url="https://github.com/test/repo.git",
                script="echo hello",
                runtime="bash",
                commit_msg="Test commit",
                push=True,
            )

        assert result["status"] == "SUCCESS"
        assert result["pushed"] is False
        assert result["exit_code"] == 0
        mock_rmtree.assert_called_once_with(tmp_dir)

    @patch("coding_agent.docker_runner.subprocess.run")
    @patch("coding_agent.docker_runner.tempfile.mkdtemp")
    @patch("coding_agent.docker_runner.shutil.rmtree")
    def test_lifecycle_git_commit_fails(self, mock_rmtree, mock_mkdtemp, mock_run):
        """If git commit fails, should mark as failed and still cleanup."""
        tmp_dir = "/tmp/test-commit-fail"
        mock_mkdtemp.return_value = tmp_dir

        clone_result = MagicMock(returncode=0)
        docker_result = MagicMock(returncode=0, stdout="done", stderr="")
        status_result = MagicMock(returncode=0, stdout="M file.py\n")
        add_result = MagicMock(returncode=0)
        # Commit fails
        commit_result = MagicMock(returncode=1, stderr="nothing to commit")

        mock_run.side_effect = [clone_result, docker_result, status_result, add_result, commit_result]

        with patch("coding_agent.docker_runner.os.path.exists", return_value=True):
            runner = DockerRunner(timeout=60)
            result = runner.clone_and_run(
                repo_url="https://github.com/test/repo.git",
                script="echo hello",
                runtime="bash",
                commit_msg="Test commit",
                push=True,
            )

        assert result["status"] == "FAILED"
        assert result["pushed"] is False
        mock_rmtree.assert_called_once_with(tmp_dir)


class TestDockerRunnerInitialization:
    """Test DockerRunner initialization and configuration."""

    def test_init_default_timeout(self):
        """DockerRunner should accept default timeout."""
        runner = DockerRunner()
        assert runner.timeout == 30

    def test_init_custom_timeout(self):
        """DockerRunner should accept custom timeout."""
        runner = DockerRunner(timeout=120)
        assert runner.timeout == 120

    @patch("coding_agent.docker_runner.subprocess.run")
    def test_init_with_image(self, mock_run):
        """DockerRunner should accept custom image."""
        runner = DockerRunner(image="python:3.11")
        assert runner.image == "python:3.11"


class TestRunWithCloneEdgeCases:
    """Test edge cases for run_with_clone."""

    @patch("coding_agent.docker_runner.subprocess.run")
    @patch("coding_agent.docker_runner.tempfile.mkdtemp")
    @patch("coding_agent.docker_runner.shutil.rmtree")
    def test_run_with_clone_empty_script(self, mock_rmtree, mock_mkdtemp, mock_run):
        """Should handle empty script gracefully."""
        tmp_dir = "/tmp/test-empty-script"
        mock_mkdtemp.return_value = tmp_dir

        clone_result = MagicMock(returncode=0)
        docker_result = MagicMock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = [clone_result, docker_result]

        with patch("coding_agent.docker_runner.os.path.exists", return_value=True):
            runner = DockerRunner(timeout=30)
            stdout, stderr, code = runner.run_with_clone(
                repo_url="https://github.com/test/repo.git",
                script="",
                runtime="bash",
            )

        assert code == 0
        mock_rmtree.assert_called_once_with(tmp_dir)

    @patch("coding_agent.docker_runner.subprocess.run")
    @patch("coding_agent.docker_runner.tempfile.mkdtemp")
    @patch("coding_agent.docker_runner.shutil.rmtree")
    def test_run_with_clone_runtime_options(self, mock_rmtree, mock_mkdtemp, mock_run):
        """Should accept different runtime options."""
        tmp_dir = "/tmp/test-runtime"
        mock_mkdtemp.return_value = tmp_dir

        clone_result = MagicMock(returncode=0)
        docker_result = MagicMock(returncode=0, stdout="ok", stderr="")

        mock_run.side_effect = [clone_result, docker_result]

        with patch("coding_agent.docker_runner.os.path.exists", return_value=True):
            runner = DockerRunner(timeout=30)
            for runtime in ["bash", "sh", "python"]:
                mock_run.side_effect = [clone_result, docker_result]
                stdout, stderr, code = runner.run_with_clone(
                    repo_url="https://github.com/test/repo.git",
                    script="echo ok",
                    runtime=runtime,
                )
                assert code == 0

        mock_rmtree.assert_called()


class TestCloneAndRunWithoutPush:
    """Test clone_and_run without push."""

    @patch("coding_agent.docker_runner.subprocess.run")
    @patch("coding_agent.docker_runner.tempfile.mkdtemp")
    @patch("coding_agent.docker_runner.shutil.rmtree")
    def test_clone_and_run_no_push(self, mock_rmtree, mock_mkdtemp, mock_run):
        """clone_and_run with push=False should not call git push."""
        tmp_dir = "/tmp/test-no-push"
        mock_mkdtemp.return_value = tmp_dir

        clone_result = MagicMock(returncode=0)
        docker_result = MagicMock(returncode=0, stdout="done", stderr="")
        status_result = MagicMock(returncode=0, stdout="M file.py\n")
        add_result = MagicMock(returncode=0)
        commit_result = MagicMock(returncode=0)

        mock_run.side_effect = [clone_result, docker_result, status_result, add_result, commit_result]

        with patch("coding_agent.docker_runner.os.path.exists", return_value=True):
            runner = DockerRunner(timeout=60)
            result = runner.clone_and_run(
                repo_url="https://github.com/test/repo.git",
                script="echo hello > file.py",
                runtime="bash",
                commit_msg="Test commit",
                push=False,
            )

        assert result["status"] == "SUCCESS"
        assert result["pushed"] is False
        assert result["exit_code"] == 0
        # Verify push was not called
        assert mock_run.call_count == 5  # clone, docker, status, add, commit (no push)
        mock_rmtree.assert_called_once_with(tmp_dir)

    @patch("coding_agent.docker_runner.subprocess.run")
    @patch("coding_agent.docker_runner.tempfile.mkdtemp")
    @patch("coding_agent.docker_runner.shutil.rmtree")
    def test_clone_and_run_docker_script_fails(self, mock_rmtree, mock_mkdtemp, mock_run):
        """If docker script fails, should stop and not commit."""
        tmp_dir = "/tmp/test-docker-fail"
        mock_mkdtemp.return_value = tmp_dir

        clone_result = MagicMock(returncode=0)
        docker_result = MagicMock(returncode=1, stdout="", stderr="Script error")

        mock_run.side_effect = [clone_result, docker_result]

        with patch("coding_agent.docker_runner.os.path.exists", return_value=True):
            runner = DockerRunner(timeout=60)
            result = runner.clone_and_run(
                repo_url="https://github.com/test/repo.git",
                script="exit 1",
                runtime="bash",
                commit_msg="Test commit",
                push=True,
            )

        assert result["status"] == "FAILED"
        assert result["exit_code"] == 1
        # Should not call git commands
        assert mock_run.call_count == 2  # Only clone and docker
        mock_rmtree.assert_called_once_with(tmp_dir)


class TestDockerRunnerTimeout:
    """Test timeout handling in DockerRunner."""

    @patch("coding_agent.docker_runner.subprocess.run")
    @patch("coding_agent.docker_runner.tempfile.mkdtemp")
    @patch("coding_agent.docker_runner.shutil.rmtree")
    def test_timeout_passed_to_subprocess(self,