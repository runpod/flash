"""Tests for flash update command."""

import subprocess
import sys
from unittest.mock import MagicMock, Mock, patch

import pytest
import typer

from runpod_flash.cli.commands.update import (
    _build_install_command,
    _compare_versions,
    _fetch_pypi_metadata,
    _get_current_version,
    _is_uv_tool_install,
    _parse_version,
    _run_install,
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


class TestCompareVersions:
    def test_equal_same_length(self):
        assert _compare_versions((1, 5, 0), (1, 5, 0)) == 0

    def test_equal_different_length(self):
        """Core edge case: (2, 0) and (2, 0, 0) are semantically equal."""
        assert _compare_versions((2, 0), (2, 0, 0)) == 0

    def test_less_than(self):
        assert _compare_versions((1, 4, 0), (1, 5, 0)) < 0

    def test_greater_than(self):
        assert _compare_versions((2, 0, 0), (1, 9, 9)) > 0

    def test_shorter_tuple_less(self):
        assert _compare_versions((1, 9), (1, 9, 1)) < 0

    def test_shorter_tuple_greater(self):
        assert _compare_versions((2, 1), (2, 0, 0)) > 0

    def test_empty_tuples(self):
        assert _compare_versions((), ()) == 0

    def test_one_empty(self):
        assert _compare_versions((), (1,)) < 0


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

    def test_runtime_error_on_malformed_json(self):
        resp = MagicMock()
        resp.read.return_value = b"not json {{"
        resp.__enter__ = Mock(return_value=resp)
        resp.__exit__ = Mock(return_value=False)

        with patch(
            "runpod_flash.cli.commands.update.urllib.request.urlopen",
            return_value=resp,
        ):
            with pytest.raises(RuntimeError, match="unexpected response"):
                _fetch_pypi_metadata()

    def test_runtime_error_on_missing_version_key(self):
        import json as _json

        resp = MagicMock()
        resp.read.return_value = _json.dumps({"info": {}}).encode()
        resp.__enter__ = Mock(return_value=resp)
        resp.__exit__ = Mock(return_value=False)

        with patch(
            "runpod_flash.cli.commands.update.urllib.request.urlopen",
            return_value=resp,
        ):
            with pytest.raises(RuntimeError, match="missing version info"):
                _fetch_pypi_metadata()


TOOL_DIR = "/home/u/.local/share/uv/tools"


class TestIsUvToolInstall:
    @pytest.mark.parametrize(
        "description, run_result, prefix, expected",
        [
            (
                "positive: prefix under tool dir -> tool install",
                MagicMock(returncode=0, stdout=f"{TOOL_DIR}\n"),
                f"{TOOL_DIR}/runpod-flash",
                True,
            ),
            (
                "negative: venv prefix outside tool dir -> not a tool install",
                MagicMock(returncode=0, stdout=f"{TOOL_DIR}\n"),
                "/home/u/project/.venv",
                False,
            ),
            (
                "boundary: prefix equals tool dir exactly (is_relative_to self)",
                MagicMock(returncode=0, stdout=f"{TOOL_DIR}\n"),
                TOOL_DIR,
                True,
            ),
            (
                "corner: `uv tool dir` exits non-zero -> fail closed",
                MagicMock(returncode=1, stdout=""),
                "/irrelevant",
                False,
            ),
            (
                "corner: `uv tool dir` empty output -> fail closed",
                MagicMock(returncode=0, stdout="\n"),
                "/irrelevant",
                False,
            ),
        ],
    )
    def test_detection(self, description, run_result, prefix, expected):
        with (
            patch(
                "runpod_flash.cli.commands.update.subprocess.run",
                return_value=run_result,
            ),
            patch("runpod_flash.cli.commands.update.sys.prefix", prefix),
        ):
            assert _is_uv_tool_install() is expected, description

    @pytest.mark.parametrize(
        "description, exc",
        [
            (
                "corner: uv missing raises OSError -> fail closed",
                OSError("uv not found"),
            ),
            (
                "corner: `uv tool dir` times out -> fail closed",
                subprocess.TimeoutExpired(cmd="uv", timeout=10),
            ),
        ],
    )
    def test_detection_subprocess_errors(self, description, exc):
        with patch("runpod_flash.cli.commands.update.subprocess.run", side_effect=exc):
            assert _is_uv_tool_install() is False, description


class TestBuildInstallCommand:
    @pytest.mark.parametrize(
        "description, which_uv, is_tool, pinned, expected",
        [
            (
                "uv tool + pinned -> `uv tool install ==X --force`",
                "/usr/bin/uv",
                True,
                True,
                ["uv", "tool", "install", "runpod-flash==1.5.0", "--force", "--quiet"],
            ),
            (
                "uv tool + latest -> `uv tool install @latest --force` (unpinned "
                "receipt so `uv tool upgrade` keeps working)",
                "/usr/bin/uv",
                True,
                False,
                ["uv", "tool", "install", "runpod-flash@latest", "--force", "--quiet"],
            ),
            (
                "uv + venv + pinned -> `uv pip install ==X --python`",
                "/usr/bin/uv",
                False,
                True,
                [
                    "uv",
                    "pip",
                    "install",
                    "runpod-flash==1.5.0",
                    "--python",
                    sys.executable,
                    "--quiet",
                ],
            ),
            (
                "uv + venv + latest -> `uv pip install ==X --python` (no receipt "
                "to pin, so resolved version is fine)",
                "/usr/bin/uv",
                False,
                False,
                [
                    "uv",
                    "pip",
                    "install",
                    "runpod-flash==1.5.0",
                    "--python",
                    sys.executable,
                    "--quiet",
                ],
            ),
            (
                "no uv + pinned -> plain pip fallback",
                None,
                False,
                True,
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "runpod-flash==1.5.0",
                    "--quiet",
                ],
            ),
            (
                "no uv + latest -> plain pip fallback",
                None,
                False,
                False,
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "runpod-flash==1.5.0",
                    "--quiet",
                ],
            ),
        ],
    )
    def test_command_selection(self, description, which_uv, is_tool, pinned, expected):
        with (
            patch(
                "runpod_flash.cli.commands.update.shutil.which", return_value=which_uv
            ),
            patch(
                "runpod_flash.cli.commands.update._is_uv_tool_install",
                return_value=is_tool,
            ),
        ):
            assert _build_install_command("1.5.0", pinned=pinned) == expected, (
                description
            )


class TestRunInstall:
    def test_success(self):
        result = MagicMock(returncode=0, stderr="", stdout="")
        with (
            patch(
                "runpod_flash.cli.commands.update.subprocess.run", return_value=result
            ),
            patch(
                "runpod_flash.cli.commands.update._build_install_command",
                return_value=["uv", "pip", "install", "runpod-flash==1.5.0", "--quiet"],
            ),
        ):
            assert _run_install("1.5.0", pinned=True) is result

    def test_failure_raises_runtime_error_uv(self):
        result = MagicMock(returncode=1, stderr="No matching distribution")
        with (
            patch(
                "runpod_flash.cli.commands.update.subprocess.run", return_value=result
            ),
            patch(
                "runpod_flash.cli.commands.update._build_install_command",
                return_value=[
                    "uv",
                    "pip",
                    "install",
                    "runpod-flash==99.99.99",
                    "--quiet",
                ],
            ),
        ):
            with pytest.raises(RuntimeError, match="uv install failed"):
                _run_install("99.99.99", pinned=True)

    def test_externally_managed_gives_actionable_error(self):
        """PEP 668 failures point the user at a venv / uv tool install."""
        result = MagicMock(
            returncode=1,
            stderr=(
                "error: externally-managed-environment\n"
                "This environment is externally managed"
            ),
        )
        with (
            patch(
                "runpod_flash.cli.commands.update.subprocess.run", return_value=result
            ),
            patch(
                "runpod_flash.cli.commands.update._build_install_command",
                return_value=[
                    "uv",
                    "pip",
                    "install",
                    "runpod-flash==1.5.0",
                    "--python",
                    sys.executable,
                    "--quiet",
                ],
            ),
        ):
            with pytest.raises(RuntimeError) as exc_info:
                _run_install("1.5.0", pinned=False)
        message = str(exc_info.value)
        assert "externally managed" in message
        assert "uv tool install runpod-flash" in message
        assert "virtual environment" in message

    def test_failure_raises_runtime_error_pip(self):
        result = MagicMock(returncode=1, stderr="No matching distribution")
        with (
            patch(
                "runpod_flash.cli.commands.update.subprocess.run", return_value=result
            ),
            patch(
                "runpod_flash.cli.commands.update._build_install_command",
                return_value=[
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "runpod-flash==99.99.99",
                ],
            ),
        ):
            with pytest.raises(RuntimeError, match="pip install failed"):
                _run_install("99.99.99", pinned=True)

    def test_timeout_propagates(self):
        with (
            patch(
                "runpod_flash.cli.commands.update.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="uv", timeout=120),
            ),
            patch(
                "runpod_flash.cli.commands.update._build_install_command",
                return_value=["uv", "pip", "install", "runpod-flash==1.5.0", "--quiet"],
            ),
        ):
            with pytest.raises(subprocess.TimeoutExpired):
                _run_install("1.5.0", pinned=True)


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
        "run_install": MagicMock(return_value=MagicMock(returncode=0)),
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
        patch("runpod_flash.cli.commands.update._run_install", mocks["run_install"]),
    ]

    for p in patches:
        p.start()

    yield mocks

    for p in patches:
        p.stop()


class TestUpdateCommandHappyPath:
    def test_update_to_latest(self, mock_update_env):
        update_command(version=None)

        mock_update_env["run_install"].assert_called_once_with("1.5.0", pinned=False)
        # Verify success message printed
        calls = [str(c) for c in mock_update_env["console"].print.call_args_list]
        assert any("1.3.0 -> 1.5.0" in c for c in calls)

    def test_update_to_specific_version(self, mock_update_env):
        update_command(version="1.4.0")

        mock_update_env["run_install"].assert_called_once_with("1.4.0", pinned=True)

    def test_downgrade_prints_warning(self, mock_update_env):
        mock_update_env["get_version"].return_value = "1.5.0"
        mock_update_env["fetch_pypi"].return_value = (
            "1.5.0",
            {"1.3.0", "1.4.0", "1.5.0"},
        )

        update_command(version="1.3.0")

        mock_update_env["run_install"].assert_called_once_with("1.3.0", pinned=True)
        calls = [str(c) for c in mock_update_env["console"].print.call_args_list]
        assert any("downgrade" in c for c in calls)


class TestUpdateCommandAlreadyOnTarget:
    def test_already_on_latest(self, mock_update_env):
        mock_update_env["get_version"].return_value = "1.5.0"

        with pytest.raises(typer.Exit) as exc_info:
            update_command(version=None)

        assert exc_info.value.exit_code == 0
        mock_update_env["run_install"].assert_not_called()

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
        mock_update_env["run_install"].assert_not_called()
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

    def test_install_failure(self, mock_update_env):
        mock_update_env["run_install"].side_effect = RuntimeError(
            "uv install failed (exit 1): No matching distribution"
        )

        with pytest.raises(typer.Exit) as exc_info:
            update_command(version=None)

        assert exc_info.value.exit_code == 1
        calls = [str(c) for c in mock_update_env["console"].print.call_args_list]
        assert any("install failed" in c for c in calls)

    def test_install_timeout(self, mock_update_env):
        mock_update_env["run_install"].side_effect = subprocess.TimeoutExpired(
            cmd="uv", timeout=120
        )

        with pytest.raises(typer.Exit) as exc_info:
            update_command(version=None)

        assert exc_info.value.exit_code == 1
        calls = [str(c) for c in mock_update_env["console"].print.call_args_list]
        assert any("timed out" in c for c in calls)
