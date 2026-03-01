"""Tests for flash update command."""

import subprocess
from unittest.mock import MagicMock, Mock, patch

import pytest
import typer

from runpod_flash.cli.commands.update import (
    _fetch_pypi_metadata,
    _get_current_version,
    _parse_version,
    _run_pip_install,
    update_command,
)


# ---------------------------------------------------------------------------
# Unit tests for helpers
# ---------------------------------------------------------------------------


class TestGetCurrentVersion:
    def test_returns_version(self):
        with patch(
            "runpod_flash.cli.commands.update.metadata.version",
            return_value="1.3.0",
        ):
            assert _get_current_version() == "1.3.0"

    def test_returns_unknown_on_not_found(self):
        from importlib.metadata import PackageNotFoundError

        with patch(
            "runpod_flash.cli.commands.update.metadata.version",
            side_effect=PackageNotFoundError("runpod-flash"),
        ):
            assert _get_current_version() == "unknown"


class TestParseVersion:
    def test_standard_version(self):
        assert _parse_version("1.5.0") == (1, 5, 0)

    def test_two_part_version(self):
        assert _parse_version("2.0") == (2, 0)

    def test_comparison(self):
        assert _parse_version("1.4.0") < _parse_version("1.5.0")
        assert _parse_version("2.0.0") > _parse_version("1.9.9")
        assert _parse_version("1.0.0") == _parse_version("1.0.0")

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            _parse_version("not.a.version")


class TestFetchPypiMetadata:
    def _make_response(self, latest: str, releases: list[str]) -> MagicMock:
        import json

        data = {
            "info": {"version": latest},
            "releases": {v: [] for v in releases},
        }
        resp = MagicMock()
        resp.read.return_value = json.dumps(data).encode()
        resp.__enter__ = Mock(return_value=resp)
        resp.__exit__ = Mock(return_value=False)
        return resp

    def test_returns_latest_and_releases(self):
        resp = self._make_response("1.5.0", ["1.3.0", "1.4.0", "1.5.0"])
        with patch(
            "runpod_flash.cli.commands.update.urllib.request.urlopen", return_value=resp
        ):
            latest, releases = _fetch_pypi_metadata()
        assert latest == "1.5.0"
        assert releases == {"1.3.0", "1.4.0", "1.5.0"}

    def test_connection_error_on_url_error(self):
        import urllib.error

        with patch(
            "runpod_flash.cli.commands.update.urllib.request.urlopen",
            side_effect=urllib.error.URLError("DNS failure"),
        ):
            with pytest.raises(ConnectionError, match="Could not reach PyPI"):
                _fetch_pypi_metadata()

    def test_runtime_error_on_http_error(self):
        import urllib.error

        with patch(
            "runpod_flash.cli.commands.update.urllib.request.urlopen",
            side_effect=urllib.error.HTTPError(
                url="https://pypi.org",
                code=503,
                msg="Service Unavailable",
                hdrs={},
                fp=None,
            ),
        ):
            with pytest.raises(RuntimeError, match="PyPI returned HTTP 503"):
                _fetch_pypi_metadata()


class TestRunPipInstall:
    def test_success(self):
        result = MagicMock(returncode=0, stderr="", stdout="")
        with patch(
            "runpod_flash.cli.commands.update.subprocess.run", return_value=result
        ):
            assert _run_pip_install("1.5.0") is result

    def test_failure_raises_runtime_error(self):
        result = MagicMock(returncode=1, stderr="No matching distribution")
        with patch(
            "runpod_flash.cli.commands.update.subprocess.run", return_value=result
        ):
            with pytest.raises(RuntimeError, match="pip install failed"):
                _run_pip_install("99.99.99")

    def test_timeout_propagates(self):
        with patch(
            "runpod_flash.cli.commands.update.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="pip", timeout=120),
        ):
            with pytest.raises(subprocess.TimeoutExpired):
                _run_pip_install("1.5.0")


# ---------------------------------------------------------------------------
# Integration tests for update_command
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_update_env():
    """Provide mocks for console, PyPI fetch, pip install, and current version."""
    mock_console = MagicMock()
    mock_console.status.return_value.__enter__ = Mock(return_value=None)
    mock_console.status.return_value.__exit__ = Mock(return_value=False)

    mocks = {
        "console": mock_console,
        "get_version": MagicMock(return_value="1.3.0"),
        "fetch_pypi": MagicMock(return_value=("1.5.0", {"1.3.0", "1.4.0", "1.5.0"})),
        "pip_install": MagicMock(return_value=MagicMock(returncode=0)),
    }

    patches = [
        patch("runpod_flash.cli.commands.update.console", mocks["console"]),
        patch(
            "runpod_flash.cli.commands.update._get_current_version",
            mocks["get_version"],
        ),
        patch(
            "runpod_flash.cli.commands.update._fetch_pypi_metadata", mocks["fetch_pypi"]
        ),
        patch(
            "runpod_flash.cli.commands.update._run_pip_install", mocks["pip_install"]
        ),
    ]

    for p in patches:
        p.start()

    yield mocks

    for p in patches:
        p.stop()


class TestUpdateCommandHappyPath:
    def test_update_to_latest(self, mock_update_env):
        update_command(version=None)

        mock_update_env["pip_install"].assert_called_once_with("1.5.0")
        # Verify success message printed
        calls = [str(c) for c in mock_update_env["console"].print.call_args_list]
        assert any("1.3.0 -> 1.5.0" in c for c in calls)

    def test_update_to_specific_version(self, mock_update_env):
        update_command(version="1.4.0")

        mock_update_env["pip_install"].assert_called_once_with("1.4.0")

    def test_downgrade_prints_warning(self, mock_update_env):
        mock_update_env["get_version"].return_value = "1.5.0"
        mock_update_env["fetch_pypi"].return_value = (
            "1.5.0",
            {"1.3.0", "1.4.0", "1.5.0"},
        )

        update_command(version="1.3.0")

        mock_update_env["pip_install"].assert_called_once_with("1.3.0")
        calls = [str(c) for c in mock_update_env["console"].print.call_args_list]
        assert any("downgrade" in c for c in calls)


class TestUpdateCommandAlreadyOnTarget:
    def test_already_on_latest(self, mock_update_env):
        mock_update_env["get_version"].return_value = "1.5.0"

        with pytest.raises(typer.Exit) as exc_info:
            update_command(version=None)

        assert exc_info.value.exit_code == 0
        mock_update_env["pip_install"].assert_not_called()

    def test_already_on_specific_version(self, mock_update_env):
        mock_update_env["get_version"].return_value = "1.4.0"

        with pytest.raises(typer.Exit) as exc_info:
            update_command(version="1.4.0")

        assert exc_info.value.exit_code == 0


class TestUpdateCommandErrors:
    def test_version_not_found(self, mock_update_env):
        with pytest.raises(typer.Exit) as exc_info:
            update_command(version="99.0.0")

        assert exc_info.value.exit_code == 1
        mock_update_env["pip_install"].assert_not_called()
        calls = [str(c) for c in mock_update_env["console"].print.call_args_list]
        assert any("not found on PyPI" in c for c in calls)

    def test_network_error(self, mock_update_env):
        mock_update_env["fetch_pypi"].side_effect = ConnectionError("no network")

        with pytest.raises(typer.Exit) as exc_info:
            update_command(version=None)

        assert exc_info.value.exit_code == 1

    def test_http_error(self, mock_update_env):
        mock_update_env["fetch_pypi"].side_effect = RuntimeError(
            "PyPI returned HTTP 503"
        )

        with pytest.raises(typer.Exit) as exc_info:
            update_command(version=None)

        assert exc_info.value.exit_code == 1

    def test_pip_failure(self, mock_update_env):
        mock_update_env["pip_install"].side_effect = RuntimeError(
            "pip install failed (exit 1): No matching distribution"
        )

        with pytest.raises(typer.Exit) as exc_info:
            update_command(version=None)

        assert exc_info.value.exit_code == 1
        calls = [str(c) for c in mock_update_env["console"].print.call_args_list]
        assert any("pip install failed" in c for c in calls)

    def test_pip_timeout(self, mock_update_env):
        mock_update_env["pip_install"].side_effect = subprocess.TimeoutExpired(
            cmd="pip", timeout=120
        )

        with pytest.raises(typer.Exit) as exc_info:
            update_command(version=None)

        assert exc_info.value.exit_code == 1
        calls = [str(c) for c in mock_update_env["console"].print.call_args_list]
        assert any("timed out" in c for c in calls)
