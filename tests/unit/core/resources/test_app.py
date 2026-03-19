"""Tests for core/resources/app.py - FlashApp resource."""

import gzip
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import SSLError, Timeout

from runpod_flash.core.resources.app import (
    FlashApp,
    FlashEnvironmentNotFoundError,
    _is_cert_verification_error,
    _upload_tarball,
    _validate_exclusive_params,
    _validate_tarball_file,
)


class TestValidateExclusiveParams:
    """Test _validate_exclusive_params helper."""

    def test_one_provided(self):
        """No error when exactly one param is provided."""
        _validate_exclusive_params("value", None, "a", "b")
        _validate_exclusive_params(None, "value", "a", "b")

    def test_both_provided_raises(self):
        with pytest.raises(ValueError, match="exactly one"):
            _validate_exclusive_params("a", "b", "name_a", "name_b")

    def test_neither_provided_raises(self):
        with pytest.raises(ValueError, match="exactly one"):
            _validate_exclusive_params(None, None, "name_a", "name_b")

    def test_both_empty_string_raises(self):
        with pytest.raises(ValueError, match="exactly one"):
            _validate_exclusive_params("", "", "name_a", "name_b")


class TestValidateTarballFile:
    """Test _validate_tarball_file function."""

    def test_valid_tarball(self, tmp_path):
        """Accepts valid gzipped tarball."""
        tar_path = tmp_path / "build.tar.gz"
        # Write gzip magic bytes + some data
        with gzip.open(tar_path, "wb") as f:
            f.write(b"fake tarball content")

        _validate_tarball_file(tar_path)  # Should not raise

    def test_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="not found"):
            _validate_tarball_file(tmp_path / "nonexistent.tar.gz")

    def test_directory_not_file(self, tmp_path):
        with pytest.raises(ValueError, match="not a file"):
            _validate_tarball_file(tmp_path)

    def test_invalid_extension(self, tmp_path):
        bad_file = tmp_path / "build.zip"
        bad_file.write_bytes(b"\x1f\x8b" + b"\x00" * 100)
        with pytest.raises(ValueError, match="Invalid file extension"):
            _validate_tarball_file(bad_file)

    def test_tgz_extension_accepted(self, tmp_path):
        """Accepts .tgz extension."""
        tar_path = tmp_path / "build.tgz"
        with gzip.open(tar_path, "wb") as f:
            f.write(b"data")
        _validate_tarball_file(tar_path)

    def test_invalid_magic_bytes(self, tmp_path):
        tar_path = tmp_path / "build.tar.gz"
        tar_path.write_bytes(b"PK\x03\x04")  # ZIP magic bytes
        with pytest.raises(ValueError, match="not a valid gzip file"):
            _validate_tarball_file(tar_path)

    def test_empty_file(self, tmp_path):
        tar_path = tmp_path / "build.tar.gz"
        tar_path.write_bytes(b"")
        with pytest.raises(ValueError, match="not a valid gzip"):
            _validate_tarball_file(tar_path)

    def test_file_too_large(self, tmp_path):
        """Rejects files exceeding MAX_TARBALL_SIZE_MB."""
        tar_path = tmp_path / "build.tar.gz"
        with gzip.open(tar_path, "wb") as f:
            f.write(b"data")

        real_stat = Path.stat

        def fake_stat(self, *args, **kwargs):
            result = real_stat(self, *args, **kwargs)
            # Return a mock with huge size but real st_mode for is_file()
            mock_result = MagicMock(wraps=result)
            mock_result.st_size = 1600 * 1024 * 1024  # 1600MB
            mock_result.st_mode = result.st_mode
            return mock_result

        with patch.object(Path, "stat", fake_stat):
            with pytest.raises(ValueError, match="exceeds maximum size"):
                _validate_tarball_file(tar_path)


class TestFlashAppInit:
    """Test FlashApp constructor."""

    def test_basic_init(self):
        app = FlashApp("my-app")
        assert app.name == "my-app"
        assert app.id == ""
        assert app._hydrated is False
        assert app.resources == {}

    def test_init_with_id(self):
        app = FlashApp("my-app", id="app-123")
        assert app.id == "app-123"


class TestFlashAppHydrate:
    """Test FlashApp._hydrate method."""

    @pytest.mark.asyncio
    async def test_hydrate_finds_existing_app(self):
        app = FlashApp("my-app")
        with patch("runpod_flash.core.resources.app.RunpodGraphQLClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.get_flash_app_by_name.return_value = {"id": "app-123"}
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            await app._hydrate()
            assert app.id == "app-123"
            assert app._hydrated is True

    @pytest.mark.asyncio
    async def test_hydrate_creates_new_app(self):
        app = FlashApp("new-app")
        with patch("runpod_flash.core.resources.app.RunpodGraphQLClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.get_flash_app_by_name.side_effect = Exception("App not found")
            mock_instance.create_flash_app.return_value = {"id": "new-app-id"}
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            await app._hydrate()
            assert app.id == "new-app-id"
            assert app._hydrated is True

    @pytest.mark.asyncio
    async def test_hydrate_id_mismatch_raises(self):
        app = FlashApp("my-app", id="wrong-id")
        with patch("runpod_flash.core.resources.app.RunpodGraphQLClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.get_flash_app_by_name.return_value = {"id": "real-id"}
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(ValueError, match="does not match"):
                await app._hydrate()

    @pytest.mark.asyncio
    async def test_hydrate_idempotent(self):
        """Second hydrate call is a no-op."""
        app = FlashApp("my-app")
        app._hydrated = True
        app.id = "app-123"

        # Should not call any API
        await app._hydrate()
        assert app.id == "app-123"

    @pytest.mark.asyncio
    async def test_hydrate_non_not_found_error_propagates(self):
        """Errors other than 'app not found' are re-raised."""
        app = FlashApp("my-app")
        with patch("runpod_flash.core.resources.app.RunpodGraphQLClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.get_flash_app_by_name.side_effect = Exception("Network error")
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(Exception, match="Network error"):
                await app._hydrate()


class TestFlashAppFactoryMethods:
    """Test FlashApp factory methods."""

    @pytest.mark.asyncio
    async def test_from_name(self):
        with patch("runpod_flash.core.resources.app.RunpodGraphQLClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.get_flash_app_by_name.return_value = {"id": "app-1"}
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            app = await FlashApp.from_name("my-app")
            assert app.name == "my-app"
            assert app.id == "app-1"

    @pytest.mark.asyncio
    async def test_create(self):
        with patch("runpod_flash.core.resources.app.RunpodGraphQLClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.create_flash_app.return_value = {"id": "app-new"}
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            app = await FlashApp.create("new-app")
            assert app.id == "app-new"

    @pytest.mark.asyncio
    async def test_get_or_create_existing(self):
        with patch("runpod_flash.core.resources.app.RunpodGraphQLClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.get_flash_app_by_name.return_value = {"id": "existing"}
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            app = await FlashApp.get_or_create("my-app")
            assert app.id == "existing"

    @pytest.mark.asyncio
    async def test_get_or_create_new(self):
        with patch("runpod_flash.core.resources.app.RunpodGraphQLClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.get_flash_app_by_name.side_effect = Exception("App not found")
            mock_instance.create_flash_app.return_value = {"id": "created"}
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            app = await FlashApp.get_or_create("new-app")
            assert app.id == "created"


class TestFlashAppUploadBuild:
    """Test FlashApp.upload_build method."""

    @pytest.mark.asyncio
    async def test_upload_missing_manifest(self, tmp_path):
        """Raises FileNotFoundError when manifest is missing."""
        tar_path = tmp_path / "build.tar.gz"
        with gzip.open(tar_path, "wb") as f:
            f.write(b"data")

        app = FlashApp("my-app", id="app-1")
        app._hydrated = True

        with patch("runpod_flash.core.resources.app.Path.cwd", return_value=tmp_path):
            with pytest.raises(FileNotFoundError, match="Manifest not found"):
                await app.upload_build(tar_path)

    @pytest.mark.asyncio
    async def test_upload_invalid_manifest_json(self, tmp_path):
        """Raises ValueError when manifest is invalid JSON."""
        tar_path = tmp_path / "build.tar.gz"
        with gzip.open(tar_path, "wb") as f:
            f.write(b"data")

        manifest_dir = tmp_path / ".flash"
        manifest_dir.mkdir()
        (manifest_dir / "flash_manifest.json").write_text("not valid json{{{")

        app = FlashApp("my-app", id="app-1")
        app._hydrated = True

        with patch("runpod_flash.core.resources.app.Path.cwd", return_value=tmp_path):
            with pytest.raises(ValueError, match="Invalid manifest JSON"):
                await app.upload_build(tar_path)

    @pytest.mark.asyncio
    async def test_upload_does_not_send_authorization_header(self, tmp_path):
        """Presigned URL upload must not include Authorization header.

        R2/S3 presigned URLs carry auth in query params; an Authorization
        header causes the provider to reject the request.
        """
        tar_path = tmp_path / "build.tar.gz"
        with gzip.open(tar_path, "wb") as f:
            f.write(b"tarball content")

        manifest_dir = tmp_path / ".flash"
        manifest_dir.mkdir()
        (manifest_dir / "flash_manifest.json").write_text('{"version": "1.0"}')

        app = FlashApp("my-app", id="app-1")
        app._hydrated = True

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.close = MagicMock()

        with (
            patch("runpod_flash.core.resources.app.Path.cwd", return_value=tmp_path),
            patch.object(
                app,
                "_get_tarball_upload_url",
                new_callable=AsyncMock,
                return_value={
                    "uploadUrl": "https://r2.example.com/presigned?token=abc",
                    "objectKey": "builds/obj-123",
                },
            ),
            patch(
                "requests.put",
                return_value=mock_resp,
            ) as mock_put,
            patch.object(
                app,
                "_finalize_upload_build",
                new_callable=AsyncMock,
                return_value={"status": "ok"},
            ),
        ):
            await app.upload_build(tar_path)

            mock_put.assert_called_once()
            _, kwargs = mock_put.call_args
            headers = kwargs["headers"]
            assert "Authorization" not in headers

    @pytest.mark.asyncio
    async def test_upload_sends_correct_headers(self, tmp_path):
        """Upload must include User-Agent and Content-Type headers."""
        tar_path = tmp_path / "build.tar.gz"
        with gzip.open(tar_path, "wb") as f:
            f.write(b"tarball content")

        manifest_dir = tmp_path / ".flash"
        manifest_dir.mkdir()
        (manifest_dir / "flash_manifest.json").write_text('{"version": "1.0"}')

        app = FlashApp("my-app", id="app-1")
        app._hydrated = True

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.close = MagicMock()

        with (
            patch("runpod_flash.core.resources.app.Path.cwd", return_value=tmp_path),
            patch.object(
                app,
                "_get_tarball_upload_url",
                new_callable=AsyncMock,
                return_value={
                    "uploadUrl": "https://r2.example.com/presigned",
                    "objectKey": "builds/obj-456",
                },
            ),
            patch(
                "requests.put",
                return_value=mock_resp,
            ) as mock_put,
            patch.object(
                app,
                "_finalize_upload_build",
                new_callable=AsyncMock,
                return_value={"status": "ok"},
            ),
        ):
            await app.upload_build(tar_path)

            _, kwargs = mock_put.call_args
            headers = kwargs["headers"]
            assert headers["Content-Type"] == "application/gzip"
            assert "User-Agent" in headers

    @pytest.mark.asyncio
    async def test_upload_puts_to_presigned_url(self, tmp_path):
        """Upload must PUT tarball data to the presigned URL."""
        tar_path = tmp_path / "build.tar.gz"
        with gzip.open(tar_path, "wb") as f:
            f.write(b"tarball content")

        manifest_dir = tmp_path / ".flash"
        manifest_dir.mkdir()
        (manifest_dir / "flash_manifest.json").write_text('{"version": "1.0"}')

        app = FlashApp("my-app", id="app-1")
        app._hydrated = True

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.close = MagicMock()

        presigned_url = "https://r2.example.com/bucket/key?X-Amz-Signature=abc"

        with (
            patch("runpod_flash.core.resources.app.Path.cwd", return_value=tmp_path),
            patch.object(
                app,
                "_get_tarball_upload_url",
                new_callable=AsyncMock,
                return_value={
                    "uploadUrl": presigned_url,
                    "objectKey": "builds/obj-789",
                },
            ),
            patch(
                "requests.put",
                return_value=mock_resp,
            ) as mock_put,
            patch.object(
                app,
                "_finalize_upload_build",
                new_callable=AsyncMock,
                return_value={"status": "ok"},
            ),
        ):
            await app.upload_build(tar_path)

            args, kwargs = mock_put.call_args
            assert args[0] == presigned_url
            assert kwargs["data"] is not None


class TestFlashAppEnvironment:
    """Test environment-related methods."""

    @pytest.mark.asyncio
    async def test_get_environment_by_name_not_found(self):
        app = FlashApp("my-app", id="app-1")
        app._hydrated = True

        with patch("runpod_flash.core.resources.app.RunpodGraphQLClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.get_flash_environment_by_name.side_effect = Exception(
                "Environment not found"
            )
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(FlashEnvironmentNotFoundError):
                await app.get_environment_by_name("nonexistent")

    @pytest.mark.asyncio
    async def test_get_environment_by_name_success(self):
        app = FlashApp("my-app", id="app-1")
        app._hydrated = True

        with patch("runpod_flash.core.resources.app.RunpodGraphQLClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.get_flash_environment_by_name.return_value = {
                "id": "env-1",
                "name": "staging",
            }
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await app.get_environment_by_name("staging")
            assert result["name"] == "staging"

    @pytest.mark.asyncio
    async def test_get_environment_by_name_none_result(self):
        """Returns FlashEnvironmentNotFoundError when result is None."""
        app = FlashApp("my-app", id="app-1")
        app._hydrated = True

        with patch("runpod_flash.core.resources.app.RunpodGraphQLClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.get_flash_environment_by_name.return_value = None
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(FlashEnvironmentNotFoundError):
                await app.get_environment_by_name("nonexistent")

    @pytest.mark.asyncio
    async def test_create_environment(self):
        app = FlashApp("my-app", id="app-1")
        app._hydrated = True

        with patch("runpod_flash.core.resources.app.RunpodGraphQLClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.create_flash_environment.return_value = {
                "id": "env-new",
                "name": "production",
            }
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await app.create_environment("production")
            assert result["id"] == "env-new"


class TestIsCertVerificationError:
    """Test _is_cert_verification_error classifier."""

    def test_detects_cert_verify_failed(self):
        exc = SSLError(
            "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: "
            "unable to get local issuer certificate"
        )
        assert _is_cert_verification_error(exc) is True

    def test_ignores_bad_record_mac(self):
        exc = SSLError("[SSL: SSLV3_ALERT_BAD_RECORD_MAC] ssl/tls alert bad record mac")
        assert _is_cert_verification_error(exc) is False

    def test_ignores_generic_ssl_error(self):
        exc = SSLError("connection reset by peer")
        assert _is_cert_verification_error(exc) is False


class TestUploadTarball:
    """Test _upload_tarball retry and error handling."""

    def _make_tarball(self, tmp_path: Path) -> Path:
        tar_path = tmp_path / "build.tar.gz"
        with gzip.open(tar_path, "wb") as f:
            f.write(b"tarball content")
        return tar_path

    @patch("runpod_flash.core.resources.app.UPLOAD_MAX_RETRIES", 3)
    def test_success_on_first_attempt(self, tmp_path):
        tar_path = self._make_tarball(tmp_path)
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.close = MagicMock()

        with patch("requests.put", return_value=mock_resp) as mock_put:
            _upload_tarball(tar_path, "https://example.com/upload", 100)

        mock_put.assert_called_once()
        mock_resp.raise_for_status.assert_called_once()

    @patch("runpod_flash.core.resources.app.UPLOAD_MAX_RETRIES", 3)
    def test_retries_on_ssl_error_then_succeeds(self, tmp_path):
        tar_path = self._make_tarball(tmp_path)
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.close = MagicMock()

        ssl_exc = SSLError("[SSL: SSLV3_ALERT_BAD_RECORD_MAC] bad record mac")

        with (
            patch("requests.put", side_effect=[ssl_exc, mock_resp]) as mock_put,
            patch("time.sleep") as mock_sleep,
        ):
            _upload_tarball(tar_path, "https://example.com/upload", 100)

        assert mock_put.call_count == 2
        mock_sleep.assert_called_once()

    @patch("runpod_flash.core.resources.app.UPLOAD_MAX_RETRIES", 3)
    def test_retries_on_connection_error(self, tmp_path):
        tar_path = self._make_tarball(tmp_path)
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.close = MagicMock()

        conn_exc = RequestsConnectionError("Connection reset by peer")

        with (
            patch("requests.put", side_effect=[conn_exc, mock_resp]) as mock_put,
            patch("time.sleep"),
        ):
            _upload_tarball(tar_path, "https://example.com/upload", 100)

        assert mock_put.call_count == 2

    @patch("runpod_flash.core.resources.app.UPLOAD_MAX_RETRIES", 3)
    def test_retries_on_timeout(self, tmp_path):
        tar_path = self._make_tarball(tmp_path)
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.close = MagicMock()

        timeout_exc = Timeout("Read timed out")

        with (
            patch("requests.put", side_effect=[timeout_exc, mock_resp]) as mock_put,
            patch("time.sleep"),
        ):
            _upload_tarball(tar_path, "https://example.com/upload", 100)

        assert mock_put.call_count == 2

    @patch("runpod_flash.core.resources.app.UPLOAD_MAX_RETRIES", 2)
    def test_raises_after_exhausting_retries(self, tmp_path):
        tar_path = self._make_tarball(tmp_path)
        ssl_exc = SSLError("[SSL: SSLV3_ALERT_BAD_RECORD_MAC] bad record mac")

        with (
            patch("requests.put", side_effect=ssl_exc) as mock_put,
            patch("time.sleep"),
            pytest.raises(SSLError, match="bad record mac"),
        ):
            _upload_tarball(tar_path, "https://example.com/upload", 100)

        assert mock_put.call_count == 2

    @patch("runpod_flash.core.resources.app.UPLOAD_MAX_RETRIES", 3)
    def test_cert_verification_error_not_retried(self, tmp_path):
        tar_path = self._make_tarball(tmp_path)
        cert_exc = SSLError(
            "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed"
        )

        with (
            patch("requests.put", side_effect=cert_exc) as mock_put,
            pytest.raises(SSLError, match="CA certificates"),
        ):
            _upload_tarball(tar_path, "https://example.com/upload", 100)

        # no retry, fails immediately
        mock_put.assert_called_once()

    @patch("runpod_flash.core.resources.app.UPLOAD_MAX_RETRIES", 3)
    def test_sends_content_length_header(self, tmp_path):
        tar_path = self._make_tarball(tmp_path)
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.close = MagicMock()

        with patch("requests.put", return_value=mock_resp) as mock_put:
            _upload_tarball(tar_path, "https://example.com/upload", 12345)

        _, kwargs = mock_put.call_args
        assert kwargs["headers"]["Content-Length"] == "12345"

    @patch("runpod_flash.core.resources.app.UPLOAD_MAX_RETRIES", 3)
    def test_sets_timeout(self, tmp_path):
        tar_path = self._make_tarball(tmp_path)
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.close = MagicMock()

        with patch("requests.put", return_value=mock_resp) as mock_put:
            _upload_tarball(tar_path, "https://example.com/upload", 100)

        _, kwargs = mock_put.call_args
        assert kwargs["timeout"] == 600

    @patch("runpod_flash.core.resources.app.UPLOAD_MAX_RETRIES", 3)
    def test_no_authorization_header(self, tmp_path):
        tar_path = self._make_tarball(tmp_path)
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.close = MagicMock()

        with patch("requests.put", return_value=mock_resp) as mock_put:
            _upload_tarball(tar_path, "https://example.com/upload", 100)

        _, kwargs = mock_put.call_args
        assert "Authorization" not in kwargs["headers"]
