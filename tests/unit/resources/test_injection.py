"""Unit tests for process injection utilities."""

from runpod_flash.core.resources.injection import build_injection_cmd


class TestBuildInjectionCmd:
    """Test build_injection_cmd() output format."""

    def test_default_remote_url(self):
        """Test default remote URL generation."""
        cmd = build_injection_cmd(worker_version="1.1.1")

        assert cmd.startswith("bash -c '")
        assert "FW_VER=1.1.1" in cmd
        assert "runpod-workers/flash/releases/download/v1.1.1/" in cmd
        assert "bootstrap.sh'" in cmd

    def test_custom_tarball_url(self):
        """Test custom tarball URL."""
        url = "https://example.com/worker.tar.gz"
        cmd = build_injection_cmd(worker_version="2.0.0", tarball_url=url)

        assert "FW_VER=2.0.0" in cmd
        assert url in cmd

    def test_file_url_for_local_testing(self):
        """Test file:// URL generates local extraction command."""
        cmd = build_injection_cmd(
            worker_version="1.0.0",
            tarball_url="file:///tmp/flash-worker.tar.gz",
        )

        assert "tar xzf /tmp/flash-worker.tar.gz" in cmd
        assert "curl" not in cmd
        assert "wget" not in cmd
        assert "bootstrap.sh'" in cmd

    def test_version_caching_logic(self):
        """Test that version-based cache check is included."""
        cmd = build_injection_cmd(worker_version="1.1.1")

        # Should check .version file
        assert ".version" in cmd
        assert "FW_VER" in cmd

    def test_network_volume_caching(self):
        """Test network volume cache path is included."""
        cmd = build_injection_cmd(worker_version="1.1.1")

        assert "/runpod-volume/.flash-worker/" in cmd
        assert "NV_CACHE" in cmd

    def test_curl_wget_python_fallback(self):
        """Test curl/wget/python3 fallback chain."""
        cmd = build_injection_cmd(worker_version="1.0.0")

        assert "curl -sSL" in cmd
        assert "wget -qO-" in cmd
        assert "urllib.request" in cmd

    def test_default_uses_constants(self):
        """Test that calling with no args uses module-level constants."""
        from runpod_flash.core.resources.constants import FLASH_WORKER_VERSION

        cmd = build_injection_cmd()

        assert f"FW_VER={FLASH_WORKER_VERSION}" in cmd
        assert f"v{FLASH_WORKER_VERSION}" in cmd

    def test_strip_components_in_remote_extraction(self):
        """Test tar uses --strip-components=1 for remote downloads."""
        cmd = build_injection_cmd(worker_version="1.0.0")

        assert "--strip-components=1" in cmd

    def test_strip_components_in_local_extraction(self):
        """Test tar uses --strip-components=1 for local file extraction."""
        cmd = build_injection_cmd(
            worker_version="1.0.0",
            tarball_url="file:///tmp/fw.tar.gz",
        )

        assert "--strip-components=1" in cmd
