"""Unit tests for flash build command."""

import json
from unittest.mock import MagicMock, patch

from runpod_flash.cli.commands.build import (
    extract_package_name,
    run_build,
    should_exclude_package,
)


class TestExtractPackageName:
    """Tests for extract_package_name function."""

    def test_simple_package_name(self):
        """Test extraction from simple package name."""
        assert extract_package_name("torch") == "torch"

    def test_package_with_version_operator(self):
        """Test extraction from package with version operator."""
        assert extract_package_name("torch>=2.0.0") == "torch"
        assert extract_package_name("numpy==1.24.0") == "numpy"
        assert extract_package_name("pandas<2.0") == "pandas"
        assert extract_package_name("scipy!=1.10.0") == "scipy"

    def test_package_with_extras(self):
        """Test extraction from package with extras."""
        assert extract_package_name("numpy[extra]") == "numpy"
        assert extract_package_name("requests[security,socks]") == "requests"

    def test_package_with_environment_marker(self):
        """Test extraction from package with environment marker."""
        assert extract_package_name('torch>=2.0; python_version>"3.8"') == "torch"

    def test_package_with_multiple_specifiers(self):
        """Test extraction from package with multiple specifiers."""
        assert extract_package_name("torch>=2.0.0,<3.0.0") == "torch"

    def test_package_with_hyphens(self):
        """Test extraction from package with hyphens."""
        assert extract_package_name("scikit-learn>=1.0.0") == "scikit-learn"

    def test_package_with_underscores(self):
        """Test extraction from package with underscores."""
        assert extract_package_name("torch_geometric>=2.0") == "torch_geometric"

    def test_case_normalization(self):
        """Test that package names are lowercased."""
        assert extract_package_name("PyTorch>=2.0") == "pytorch"
        assert extract_package_name("NUMPY") == "numpy"

    def test_whitespace_handling(self):
        """Test that leading/trailing whitespace is handled."""
        assert extract_package_name("  torch  >=2.0.0") == "torch"


class TestShouldExcludePackage:
    """Tests for should_exclude_package function."""

    def test_exact_match(self):
        """Test exact package name match."""
        assert should_exclude_package("torch>=2.0.0", ["torch", "numpy"])
        assert should_exclude_package("numpy==1.24.0", ["torch", "numpy"])

    def test_no_match(self):
        """Test when package does not match."""
        assert not should_exclude_package("scipy>=1.0", ["torch", "numpy"])
        assert not should_exclude_package("pandas", ["torch"])

    def test_case_insensitive(self):
        """Test case-insensitive matching."""
        assert should_exclude_package("TORCH>=2.0", ["torch"])
        # Note: exclusions are normalized to lowercase by the caller
        assert should_exclude_package("torch>=2.0", ["torch"])

    def test_no_false_positive_on_prefix(self):
        """Test that torch-vision doesn't match torch exclusion."""
        assert not should_exclude_package("torch-vision>=0.15", ["torch"])
        assert not should_exclude_package("torchvision>=0.15", ["torch"])

    def test_exclusion_with_extras(self):
        """Test exclusion with extras in requirement."""
        assert should_exclude_package("torch[cuda]>=2.0", ["torch"])

    def test_empty_exclusions(self):
        """Test with empty exclusion list."""
        assert not should_exclude_package("torch>=2.0", [])

    def test_multiple_exclusions(self):
        """Test with multiple exclusions."""
        exclusions = ["torch", "torchvision", "torchaudio"]
        assert should_exclude_package("torch>=2.0", exclusions)
        assert should_exclude_package("torchvision>=0.15", exclusions)
        assert should_exclude_package("torchaudio>=2.0", exclusions)
        assert not should_exclude_package("numpy>=1.24", exclusions)


class TestPackageExclusionIntegration:
    """Integration tests for package exclusion logic."""

    def test_filter_requirements_with_exclusions(self):
        """Test filtering requirements with exclusions."""
        requirements = [
            "torch>=2.0.0",
            "torchvision>=0.15.0",
            "numpy>=1.24.0",
            "pandas>=2.0.0",
        ]
        exclusions = ["torch", "torchvision"]

        filtered = [
            req for req in requirements if not should_exclude_package(req, exclusions)
        ]

        assert len(filtered) == 2
        assert "numpy>=1.24.0" in filtered
        assert "pandas>=2.0.0" in filtered
        assert "torch>=2.0.0" not in filtered
        assert "torchvision>=0.15.0" not in filtered

    def test_track_matched_exclusions(self):
        """Test tracking which exclusions matched."""
        requirements = [
            "torch>=2.0.0",
            "numpy>=1.24.0",
        ]
        exclusions = ["torch", "scipy", "pandas"]

        matched = set()
        for req in requirements:
            if should_exclude_package(req, exclusions):
                pkg_name = extract_package_name(req)
                matched.add(pkg_name)

        # Only torch should match
        assert matched == {"torch"}

        # scipy and pandas didn't match
        unmatched = set(exclusions) - matched
        assert unmatched == {"scipy", "pandas"}


class TestRunBuildHandlerGeneration:
    """Tests for QB handler generation in the build pipeline."""

    def test_run_build_calls_handler_generator(self, tmp_path):
        """Test that run_build invokes HandlerGenerator.generate_handlers()."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        # Create minimal Python file with @remote decorator
        worker_file = project_dir / "worker.py"
        worker_file.write_text(
            "from runpod_flash import remote, LiveServerless\n"
            "gpu = LiveServerless()\n"
            "@remote(gpu)\n"
            "def my_func(prompt: str) -> str:\n"
            "    return prompt\n"
        )

        mock_handler_gen = MagicMock()
        mock_lb_gen = MagicMock()

        with (
            patch(
                "runpod_flash.cli.commands.build.HandlerGenerator",
                return_value=mock_handler_gen,
            ) as mock_handler_cls,
            patch(
                "runpod_flash.cli.commands.build.LBHandlerGenerator",
                return_value=mock_lb_gen,
            ),
            patch(
                "runpod_flash.cli.commands.build.install_dependencies",
                return_value=True,
            ),
        ):
            run_build(project_dir, "test_app", no_deps=True)

        mock_handler_cls.assert_called_once()
        mock_handler_gen.generate_handlers.assert_called_once()

    def test_run_build_produces_qb_handler_files(self, tmp_path):
        """Test that run_build produces handler_<name>.py files for QB resources."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        worker_file = project_dir / "worker.py"
        worker_file.write_text(
            "from runpod_flash import remote, LiveServerless\n"
            "gpu = LiveServerless()\n"
            "@remote(gpu)\n"
            "def my_func(prompt: str) -> str:\n"
            "    return prompt\n"
        )

        with patch(
            "runpod_flash.cli.commands.build.install_dependencies",
            return_value=True,
        ):
            run_build(project_dir, "test_app", no_deps=True)

        build_dir = project_dir / ".flash" / ".build"
        handler_files = list(build_dir.glob("handler_*.py"))
        assert len(handler_files) >= 1

        # Verify handler file content uses deployed template (is_live_resource=False for non-Live resources)
        handler_content = handler_files[0].read_text()
        assert "handler" in handler_content

    def test_run_build_manifest_includes_handler_file(self, tmp_path):
        """Test that run_build manifest includes handler_file for QB resources."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        worker_file = project_dir / "worker.py"
        worker_file.write_text(
            "from runpod_flash import remote, LiveServerless\n"
            "gpu = LiveServerless()\n"
            "@remote(gpu)\n"
            "def my_func(prompt: str) -> str:\n"
            "    return prompt\n"
        )

        with patch(
            "runpod_flash.cli.commands.build.install_dependencies",
            return_value=True,
        ):
            run_build(project_dir, "test_app", no_deps=True)

        manifest_path = project_dir / ".flash" / "flash_manifest.json"
        assert manifest_path.exists()

        manifest = json.loads(manifest_path.read_text())
        for resource_name, resource_data in manifest["resources"].items():
            if not resource_data.get("is_load_balanced", False):
                assert "handler_file" in resource_data
                assert resource_data["handler_file"] == f"handler_{resource_name}.py"
