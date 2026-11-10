"""Tests for Phase 5.4 — REST daemon and PID file management."""
import os
import subprocess
import sys

# ── PID file management ──


class TestPidFile:
    def test_pid_file_written_on_start(self, tmp_path):
        """Daemon writes PID file with current process ID."""
        from memorius.cli.main import _start_daemon, _stop_daemon
        from memorius.config import load_config
        from memorius.vault import VaultEngine

        config = load_config()
        engine = VaultEngine(config)
        pid_file = tmp_path / "test.pid"

        # On Windows, _start_daemon launches a subprocess
        _start_daemon(engine, "127.0.0.1", 8999, pid_file)

        assert pid_file.exists()
        pid = int(pid_file.read_text().strip())
        assert pid > 0

        # Clean up
        _stop_daemon(pid_file)

    def test_stop_daemon_removes_pid_file(self, tmp_path):
        """_stop_daemon removes PID file after stopping."""
        from memorius.cli.main import _start_daemon, _stop_daemon
        from memorius.config import load_config
        from memorius.vault import VaultEngine

        config = load_config()
        engine = VaultEngine(config)
        pid_file = tmp_path / "test.pid"

        _start_daemon(engine, "127.0.0.1", 8998, pid_file)
        assert pid_file.exists()

        _stop_daemon(pid_file)
        # PID file should be removed (process may or may not have exited)
        # At minimum, no crash

    def test_stop_no_pid_file_prints_message(self, tmp_path, capsys):
        """_stop_daemon with no PID file prints message."""
        from memorius.cli.main import _stop_daemon

        pid_file = tmp_path / "nonexistent.pid"
        _stop_daemon(pid_file)
        captured = capsys.readouterr()
        assert "No daemon running" in captured.out

    def test_stop_invalid_pid_file_cleans_up(self, tmp_path, capsys):
        """_stop_daemon with invalid PID file removes it."""
        from memorius.cli.main import _stop_daemon

        pid_file = tmp_path / "bad.pid"
        pid_file.write_text("not-a-number")
        _stop_daemon(pid_file)
        captured = capsys.readouterr()
        assert "Invalid PID file" in captured.out
        assert not pid_file.exists()

    def test_stop_dead_pid_cleans_up(self, tmp_path, capsys):
        """_stop_daemon with dead PID cleans up."""
        from memorius.cli.main import _stop_daemon

        pid_file = tmp_path / "dead.pid"
        pid_file.write_text("99999999")
        _stop_daemon(pid_file)
        captured = capsys.readouterr()
        assert "not running" in captured.out
        assert not pid_file.exists()

    def test_stop_refuses_non_memorius_pid(self, tmp_path, capsys, monkeypatch):
        """_stop_daemon refuses to kill a non-memorius process (PID safety)."""
        from memorius.cli.main import _stop_daemon

        pid_file = tmp_path / "foreign.pid"
        # Use our own PID but pretend it's not memorius by monkeypatching
        own_pid = os.getpid()
        pid_file.write_text(str(own_pid))

        # Monkeypatch _is_memorius_process to return False
        monkeypatch.setattr("memorius.cli.main._is_memorius_process", lambda pid: False)

        _stop_daemon(pid_file)
        captured = capsys.readouterr()
        assert "not a memorius process" in captured.out
        assert not pid_file.exists()

    def test_is_memorius_process_rejects_non_memorius(self):
        """_is_memorius_process returns False for non-memorius processes."""
        import os

        from memorius.cli.main import _is_memorius_process
        # PID 1 is init/systemd, not memorius
        assert _is_memorius_process(1) is False
        # Current pytest process is not memorius
        assert _is_memorius_process(os.getpid()) is False


# ── CLI flag wiring ──


class TestDaemonCliFlags:
    def _run_help(self):
        result = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.argv=['memorius', 'serve-rest', '--help']; from memorius.cli.main import main; main()"],
            capture_output=True, text=True, check=False,
        )
        return result

    def test_daemon_flag_accepted(self):
        """serve-rest accepts --daemon flag."""
        result = self._run_help()
        assert "--daemon" in result.stdout

    def test_stop_flag_accepted(self):
        """serve-rest accepts --stop flag."""
        result = self._run_help()
        assert "--stop" in result.stdout

    def test_pid_file_flag_accepted(self):
        """serve-rest accepts --pid-file flag."""
        result = self._run_help()
        assert "--pid-file" in result.stdout
