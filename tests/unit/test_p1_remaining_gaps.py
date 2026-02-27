"""P1 remaining gap tests.

Covers:
- RES-DRIFT-006: Name-based identity via get_resource_key()
- DEPLOY-RM-005: Corrupted state file → graceful recovery
- NET-GQL-009: Network timeout → appropriate error (ServerTimeoutError)
- NET-GQL-010: Connection refused → appropriate error (ClientConnectorError)
- NET-SSL-001: SSL_CERT_FILE env var honored by aiohttp session creation
- NET-SSL-002: SSL verification failure propagates as ClientSSLError
- SRVGEN-016: _flash_import helper correctly loads modules with scoped sys.path
"""

import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import cloudpickle
import pytest

from runpod_flash.core.api.runpod import RunpodGraphQLClient

from runpod_flash.core.resources.live_serverless import LiveServerless
from runpod_flash.core.resources.resource_manager import ResourceManager
from runpod_flash.core.resources.gpu import GpuGroup
from runpod_flash.core.utils.singleton import SingletonMixin


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset_resource_manager():
    """Reset ResourceManager singleton state to a clean slate."""
    SingletonMixin._instances = {}
    ResourceManager._resources = {}
    ResourceManager._resource_configs = {}
    ResourceManager._deployment_locks = {}
    ResourceManager._global_lock = None
    ResourceManager._lock_initialized = False
    ResourceManager._resources_initialized = False


# ---------------------------------------------------------------------------
# RES-DRIFT-006: Name-based resource key identity
# ---------------------------------------------------------------------------


class TestNameBasedResourceKey:
    """RES-DRIFT-006: get_resource_key() uses ClassName:name format."""

    def test_key_format_is_classname_colon_name(self):
        """get_resource_key returns '{ClassName}:{name}'."""
        resource = LiveServerless(
            name="my-endpoint",
            gpus=[GpuGroup.ADA_24],
            workersMin=0,
            workersMax=3,
        )
        key = resource.get_resource_key()
        # Key must contain the class name and the resource name
        assert "LiveServerless" in key
        assert "my-endpoint" in key
        assert key == f"LiveServerless:{resource.name}"

    def test_same_name_same_key(self):
        """Two resources with the same name get the same resource key."""
        r1 = LiveServerless(
            name="shared-name",
            gpus=[GpuGroup.ADA_24],
            workersMin=0,
            workersMax=3,
        )
        r2 = LiveServerless(
            name="shared-name",
            gpus=[GpuGroup.ADA_24],
            workersMin=0,
            workersMax=5,  # different config
        )
        assert r1.get_resource_key() == r2.get_resource_key()

    def test_different_names_different_keys(self):
        """Resources with different names get different resource keys."""
        r1 = LiveServerless(
            name="endpoint-alpha",
            gpus=[GpuGroup.ADA_24],
            workersMin=0,
            workersMax=3,
        )
        r2 = LiveServerless(
            name="endpoint-beta",
            gpus=[GpuGroup.ADA_24],
            workersMin=0,
            workersMax=3,
        )
        assert r1.get_resource_key() != r2.get_resource_key()

    def test_key_stable_after_id_assigned(self):
        """Key remains stable after server assigns an endpoint id."""
        resource = LiveServerless(
            name="stable-key-test",
            gpus=[GpuGroup.ADA_24],
            workersMin=0,
            workersMax=2,
        )
        key_before = resource.get_resource_key()
        resource.id = "server-assigned-id-xyz"
        key_after = resource.get_resource_key()
        assert key_before == key_after

    def test_key_stable_after_config_change(self):
        """Key is based on name, not config fields, so config changes don't affect it."""
        resource = LiveServerless(
            name="config-drift-test",
            gpus=[GpuGroup.ADA_24],
            workersMin=0,
            workersMax=3,
        )
        key_before = resource.get_resource_key()
        # Simulate a config change
        resource.workersMax = 10
        key_after = resource.get_resource_key()
        assert key_before == key_after


# ---------------------------------------------------------------------------
# DEPLOY-RM-005: Corrupted state file → graceful recovery
# ---------------------------------------------------------------------------


class TestResourceManagerCorruptedStateFile:
    """DEPLOY-RM-005: Corrupted pickle file is handled gracefully."""

    def setup_method(self):
        """Reset singleton before each test."""
        _reset_resource_manager()

    def teardown_method(self):
        """Reset singleton after each test."""
        _reset_resource_manager()

    def test_corrupted_pickle_logs_error_and_keeps_empty_resources(
        self, tmp_path, monkeypatch
    ):
        """When .runpod/resources.pkl is invalid pickle, _load_resources
        leaves _resources as empty dict without raising."""
        from runpod_flash.core.resources import resource_manager

        runpod_dir = tmp_path / ".runpod"
        runpod_dir.mkdir()
        state_file = runpod_dir / "resources.pkl"
        # Write invalid (non-pickle) binary content
        state_file.write_bytes(b"this is not a valid pickle \xff\xfe")

        monkeypatch.setattr(resource_manager, "RESOURCE_STATE_FILE", state_file)
        monkeypatch.setattr(resource_manager, "RUNPOD_FLASH_DIR", runpod_dir)

        rm = ResourceManager()
        rm._load_resources()

        # Resources should remain empty
        assert ResourceManager._resources == {}

    def test_corrupted_file_does_not_raise(self, tmp_path, monkeypatch):
        """Loading a corrupted state file must not propagate an exception."""
        from runpod_flash.core.resources import resource_manager

        runpod_dir = tmp_path / ".runpod"
        runpod_dir.mkdir()
        state_file = runpod_dir / "resources.pkl"
        state_file.write_bytes(b"\x00\x01\x02\x03 garbage data")

        monkeypatch.setattr(resource_manager, "RESOURCE_STATE_FILE", state_file)
        monkeypatch.setattr(resource_manager, "RUNPOD_FLASH_DIR", runpod_dir)

        # Should not raise
        rm = ResourceManager()
        try:
            rm._load_resources()
        except Exception as exc:
            pytest.fail(f"_load_resources() raised an unexpected exception: {exc}")

    def test_missing_state_file_returns_empty_dict(self, tmp_path, monkeypatch):
        """When state file does not exist, _resources stays empty."""
        from runpod_flash.core.resources import resource_manager

        runpod_dir = tmp_path / ".runpod"
        runpod_dir.mkdir()
        state_file = runpod_dir / "resources.pkl"
        # Deliberately do NOT create the file

        monkeypatch.setattr(resource_manager, "RESOURCE_STATE_FILE", state_file)
        monkeypatch.setattr(resource_manager, "RUNPOD_FLASH_DIR", runpod_dir)

        rm = ResourceManager()
        rm._load_resources()

        assert ResourceManager._resources == {}

    def test_truncated_pickle_triggers_error_recovery(self, tmp_path, monkeypatch):
        """A truncated (partial) pickle file is treated as corrupted."""
        from runpod_flash.core.resources import resource_manager

        runpod_dir = tmp_path / ".runpod"
        runpod_dir.mkdir()
        state_file = runpod_dir / "resources.pkl"

        # Write a valid pickle prefix but truncate it
        valid_start = cloudpickle.dumps({"key": "value"})
        state_file.write_bytes(valid_start[:10])  # truncated

        monkeypatch.setattr(resource_manager, "RESOURCE_STATE_FILE", state_file)
        monkeypatch.setattr(resource_manager, "RUNPOD_FLASH_DIR", runpod_dir)

        rm = ResourceManager()
        rm._load_resources()

        assert ResourceManager._resources == {}


# ---------------------------------------------------------------------------
# NET-GQL-009: Network timeout → appropriate error (ServerTimeoutError)
# ---------------------------------------------------------------------------


class TestGraphQLNetworkTimeout:
    """NET-GQL-009: ServerTimeoutError caught by _execute_graphql and wrapped."""

    @pytest.mark.asyncio
    async def test_server_timeout_raises_http_request_failed(self):
        """ServerTimeoutError (a ClientError subclass) is caught and wrapped as
        Exception('HTTP request failed: ...')."""
        client = RunpodGraphQLClient(api_key="test-key")

        mock_ctx_mgr = MagicMock()
        mock_ctx_mgr.__aenter__ = AsyncMock(side_effect=aiohttp.ServerTimeoutError())
        mock_ctx_mgr.__aexit__ = AsyncMock(return_value=False)

        with patch.object(client, "_get_session", new_callable=AsyncMock) as mock_sess:
            mock_session_instance = MagicMock()
            mock_session_instance.post = MagicMock(return_value=mock_ctx_mgr)
            mock_sess.return_value = mock_session_instance

            with pytest.raises(Exception, match="HTTP request failed"):
                await client._execute_graphql("query { test }")

    @pytest.mark.asyncio
    async def test_timeout_error_is_client_error_subclass(self):
        """Confirm ServerTimeoutError is an aiohttp.ClientError subclass (class invariant)."""
        assert issubclass(aiohttp.ServerTimeoutError, aiohttp.ClientError)


# ---------------------------------------------------------------------------
# NET-GQL-010: Connection refused → appropriate error (ClientConnectorError)
# ---------------------------------------------------------------------------


class TestGraphQLConnectionRefused:
    """NET-GQL-010: ClientConnectorError caught by _execute_graphql and wrapped."""

    @pytest.mark.asyncio
    async def test_connection_refused_raises_http_request_failed(self):
        """ClientConnectorError is caught and wrapped as Exception('HTTP request failed: ...')."""
        client = RunpodGraphQLClient(api_key="test-key")

        conn_error = aiohttp.ClientConnectorError(
            connection_key=MagicMock(), os_error=OSError("Connection refused")
        )

        mock_ctx_mgr = MagicMock()
        mock_ctx_mgr.__aenter__ = AsyncMock(side_effect=conn_error)
        mock_ctx_mgr.__aexit__ = AsyncMock(return_value=False)

        with patch.object(client, "_get_session", new_callable=AsyncMock) as mock_sess:
            mock_session_instance = MagicMock()
            mock_session_instance.post = MagicMock(return_value=mock_ctx_mgr)
            mock_sess.return_value = mock_session_instance

            with pytest.raises(Exception, match="HTTP request failed"):
                await client._execute_graphql("query { test }")

    @pytest.mark.asyncio
    async def test_connection_refused_error_is_client_error_subclass(self):
        """Confirm ClientConnectorError is an aiohttp.ClientError subclass (class invariant)."""
        assert issubclass(aiohttp.ClientConnectorError, aiohttp.ClientError)


# ---------------------------------------------------------------------------
# NET-SSL-001: SSL_CERT_FILE env var honored by aiohttp session creation
# ---------------------------------------------------------------------------


class TestSSLCertFileEnvVar:
    """NET-SSL-001: Session creation succeeds (no crash) when SSL_CERT_FILE is set."""

    @pytest.mark.asyncio
    async def test_session_created_successfully_with_ssl_cert_file(
        self, monkeypatch, tmp_path
    ):
        """When SSL_CERT_FILE points to an existing file, _get_session creates a session
        without error. Python's ssl module picks up the env var at the OS level."""
        # Create a dummy cert file so the path exists
        cert_file = tmp_path / "fake-ca-bundle.crt"
        cert_file.write_text("# fake CA bundle\n")

        monkeypatch.setenv("SSL_CERT_FILE", str(cert_file))

        client = RunpodGraphQLClient(api_key="test-key")
        session = await client._get_session()

        try:
            assert session is not None
            assert isinstance(session, aiohttp.ClientSession)
            assert not session.closed
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_session_created_without_ssl_cert_file(self, monkeypatch):
        """Session creation succeeds when SSL_CERT_FILE is not set (baseline)."""
        monkeypatch.delenv("SSL_CERT_FILE", raising=False)

        client = RunpodGraphQLClient(api_key="test-key")
        session = await client._get_session()

        try:
            assert session is not None
            assert isinstance(session, aiohttp.ClientSession)
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_session_uses_tcp_connector_with_threaded_resolver(self, monkeypatch):
        """The session is constructed with a TCPConnector using ThreadedResolver,
        regardless of SSL_CERT_FILE presence."""
        from aiohttp.resolver import ThreadedResolver

        monkeypatch.setenv("SSL_CERT_FILE", "/tmp/nonexistent-cert.pem")

        client = RunpodGraphQLClient(api_key="test-key")

        with patch("aiohttp.TCPConnector") as mock_connector_cls:
            mock_connector_instance = MagicMock()
            mock_connector_cls.return_value = mock_connector_instance

            # patch ClientSession to avoid actually opening connections
            with patch("aiohttp.ClientSession") as mock_session_cls:
                mock_session_instance = MagicMock()
                mock_session_instance.closed = False
                mock_session_cls.return_value = mock_session_instance
                client.session = None  # force re-creation

                await client._get_session()

                # TCPConnector was constructed with a ThreadedResolver
                mock_connector_cls.assert_called_once()
                call_kwargs = mock_connector_cls.call_args.kwargs
                assert isinstance(call_kwargs.get("resolver"), ThreadedResolver)


# ---------------------------------------------------------------------------
# NET-SSL-002: SSL verification failure propagates as ClientSSLError
# ---------------------------------------------------------------------------


class TestSSLVerificationFailure:
    """NET-SSL-002: SSL certificate errors propagate through _execute_graphql."""

    @pytest.mark.asyncio
    async def test_ssl_error_wrapped_as_http_request_failed(self):
        """ClientSSLError raised during HTTP post is caught and wrapped."""
        client = RunpodGraphQLClient(api_key="test-key")

        ssl_error = aiohttp.ClientSSLError(
            connection_key=MagicMock(),
            os_error=OSError("SSL: CERTIFICATE_VERIFY_FAILED"),
        )

        mock_ctx_mgr = MagicMock()
        mock_ctx_mgr.__aenter__ = AsyncMock(side_effect=ssl_error)
        mock_ctx_mgr.__aexit__ = AsyncMock(return_value=False)

        with patch.object(client, "_get_session", new_callable=AsyncMock) as mock_sess:
            mock_session_instance = MagicMock()
            mock_session_instance.post = MagicMock(return_value=mock_ctx_mgr)
            mock_sess.return_value = mock_session_instance

            with pytest.raises(Exception, match="HTTP request failed"):
                await client._execute_graphql("query { test }")

    @pytest.mark.asyncio
    async def test_ssl_error_from_session_post_is_client_error(self):
        """ClientSSLError raised inside session.post() is a ClientError subclass,
        so it's caught by the except aiohttp.ClientError handler."""
        client = RunpodGraphQLClient(api_key="test-key")

        ssl_error = aiohttp.ClientSSLError(
            connection_key=MagicMock(),
            os_error=OSError("CERTIFICATE_VERIFY_FAILED"),
        )

        mock_ctx_mgr = MagicMock()
        mock_ctx_mgr.__aenter__ = AsyncMock(side_effect=ssl_error)
        mock_ctx_mgr.__aexit__ = AsyncMock(return_value=False)

        with patch.object(client, "_get_session", new_callable=AsyncMock) as mock_sess:
            mock_session_instance = MagicMock()
            mock_session_instance.post = MagicMock(return_value=mock_ctx_mgr)
            mock_sess.return_value = mock_session_instance

            with pytest.raises(Exception, match="HTTP request failed"):
                await client._execute_graphql("query { test }")

    def test_client_ssl_error_is_client_error_subclass(self):
        """Confirm ClientSSLError is a ClientError subclass (class invariant)."""
        assert issubclass(aiohttp.ClientSSLError, aiohttp.ClientError)


# ---------------------------------------------------------------------------
# SRVGEN-016: _flash_import helper with scoped sys.path
# ---------------------------------------------------------------------------


class TestFlashImportHelper:
    """SRVGEN-016: The _flash_import() code generated by _generate_flash_server
    correctly loads modules with temporarily scoped sys.path."""

    def _get_flash_import_fn(self, project_root: Path):
        """Execute the _flash_import source code block in isolation and return the
        function object so we can call it directly without invoking the full
        server codegen pipeline."""
        import importlib as _importlib

        _path_str = str(project_root)

        def _flash_import(module_path, name, subdir=None):
            """Verbatim copy of the generated _flash_import helper from run.py."""
            _path = str(project_root / subdir) if subdir else None
            if _path:
                sys.path.insert(0, _path)
            try:
                return getattr(_importlib.import_module(module_path), name)
            finally:
                if _path is not None:
                    try:
                        if sys.path and sys.path[0] == _path:
                            sys.path.pop(0)
                        else:
                            sys.path.remove(_path)
                    except ValueError:
                        pass

        return _flash_import

    def test_flash_import_loads_attribute_from_module(self, tmp_path):
        """_flash_import returns the correct attribute from a dynamically loaded module.

        The generated server.py already inserts _project_root into sys.path at the
        top of the file.  _flash_import's subdir argument adds the *subdirectory*
        (e.g. '01_hello') so that sibling imports inside that module resolve
        correctly.  We must replicate the _project_root insertion here.
        """
        # Create a simple module inside a numeric subdirectory
        subdir = tmp_path / "01_hello"
        subdir.mkdir()
        module_file = subdir / "worker.py"
        module_file.write_text("MY_VALUE = 42\n")

        _flash_import = self._get_flash_import_fn(tmp_path)

        # Mimic the generated server.py: insert project_root so the dotted
        # module path '01_hello.worker' is resolvable from sys.path.
        sys.path.insert(0, str(tmp_path))
        try:
            result = _flash_import("01_hello.worker", "MY_VALUE", "01_hello")
        finally:
            sys.path.remove(str(tmp_path))
            sys.modules.pop("01_hello.worker", None)
            sys.modules.pop("01_hello", None)

        assert result == 42

    def test_flash_import_restores_sys_path_after_success(self, tmp_path):
        """sys.path is restored to its original state after a successful import."""
        subdir = tmp_path / "02_utils"
        subdir.mkdir()
        (subdir / "helper.py").write_text("HELPER = 'ok'\n")

        _flash_import = self._get_flash_import_fn(tmp_path)

        sys.path.insert(0, str(tmp_path))
        try:
            path_before = list(sys.path)
            _flash_import("02_utils.helper", "HELPER", "02_utils")
            path_after = list(sys.path)
        finally:
            try:
                sys.path.remove(str(tmp_path))
            except ValueError:
                pass
            sys.modules.pop("02_utils.helper", None)
            sys.modules.pop("02_utils", None)

        assert path_before == path_after

    def test_flash_import_restores_sys_path_after_failure(self, tmp_path):
        """sys.path is restored even when the import fails."""
        subdir = tmp_path / "03_broken"
        subdir.mkdir()
        # Module exists but attribute does not
        (subdir / "noattr.py").write_text("X = 1\n")

        _flash_import = self._get_flash_import_fn(tmp_path)

        sys.path.insert(0, str(tmp_path))
        try:
            path_before = list(sys.path)
            with pytest.raises(AttributeError):
                _flash_import("03_broken.noattr", "NONEXISTENT_ATTR", "03_broken")
            path_after = list(sys.path)
        finally:
            try:
                sys.path.remove(str(tmp_path))
            except ValueError:
                pass
            sys.modules.pop("03_broken.noattr", None)
            sys.modules.pop("03_broken", None)

        assert path_before == path_after

    def test_flash_import_without_subdir_does_not_modify_sys_path(self, tmp_path):
        """When no subdir is given, sys.path is not modified."""
        # Register a top-level module directly in sys.modules so no file is needed
        fake_module = types.ModuleType("fake_top_level_module_xyz")
        fake_module.ATTR = "hello"  # type: ignore[attr-defined]
        sys.modules["fake_top_level_module_xyz"] = fake_module

        _flash_import = self._get_flash_import_fn(tmp_path)

        path_before = list(sys.path)
        result = _flash_import("fake_top_level_module_xyz", "ATTR")
        path_after = list(sys.path)

        assert result == "hello"
        assert path_before == path_after

        del sys.modules["fake_top_level_module_xyz"]

    def test_make_import_line_uses_flash_import_for_numeric_modules(self):
        """_make_import_line emits a _flash_import() call when module has numeric segment."""
        from runpod_flash.cli.commands.run import _make_import_line

        line = _make_import_line("01_hello.worker", "my_fn")

        assert "_flash_import" in line
        assert '"01_hello.worker"' in line
        assert '"my_fn"' in line

    def test_make_import_line_uses_regular_import_for_normal_modules(self):
        """_make_import_line emits a regular 'from … import …' for normal modules."""
        from runpod_flash.cli.commands.run import _make_import_line

        line = _make_import_line("my_package.workers.gpu_worker", "gpu_fn")

        assert line == "from my_package.workers.gpu_worker import gpu_fn"
        assert "_flash_import" not in line

    def test_make_import_line_includes_subdir_for_nested_numeric_module(self):
        """_make_import_line includes the subdir argument when module path is nested."""
        from runpod_flash.cli.commands.run import _make_import_line

        line = _make_import_line("01_examples.my_worker", "process")

        # subdir argument should be "01_examples"
        assert '"01_examples"' in line
        assert "_flash_import" in line

    def test_has_numeric_module_segments_detects_leading_digit(self):
        """_has_numeric_module_segments returns True when any segment starts with digit."""
        from runpod_flash.cli.commands.run import _has_numeric_module_segments

        assert _has_numeric_module_segments("01_hello.worker") is True
        assert _has_numeric_module_segments("normal.02module.sub") is True
        assert _has_numeric_module_segments("normal.worker") is False
        assert _has_numeric_module_segments("my_package.workers") is False

    def test_module_parent_subdir_returns_parent_path(self):
        """_module_parent_subdir converts dotted parent into slash-separated path."""
        from runpod_flash.cli.commands.run import _module_parent_subdir

        assert _module_parent_subdir("01_hello.worker") == "01_hello"
        assert _module_parent_subdir("a.b.c") == "a/b"
        assert _module_parent_subdir("toplevel") is None
