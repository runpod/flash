"""Tests for core/resources/app.py - FlashApp resource."""

import gzip
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from runpod_flash.core.resources.app import (
    FlashApp,
    FlashEnvironmentNotFoundError,
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
            mock_result.st_size = 600 * 1024 * 1024  # 600MB
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
