"""Unit tests for flash build command."""

import json
from unittest.mock import MagicMock, patch

import pytest
import typer

from runpod_flash.cli.commands.build import (
    _find_runpod_flash,
    collect_requirements,
    extract_remote_dependencies,
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


class TestExtractRemoteDependencies:
    """Tests for extracting @remote decorator dependencies."""

    def test_extracts_dependencies_from_async_remote_function(self, tmp_path):
        """Extract dependencies from async @remote function decorators."""
        workers_dir = tmp_path / "workers"
        workers_dir.mkdir()
        worker_file = workers_dir / "worker.py"

        worker_file.write_text(
            "from runpod_flash import remote, LiveServerless\n"
            "gpu = LiveServerless()\n"
            "@remote(gpu, dependencies=['torch', 'transformers'])\n"
            "async def my_async_func(prompt: str) -> str:\n"
            "    return prompt\n"
        )

        dependencies = extract_remote_dependencies(workers_dir)

        assert dependencies == ["torch", "transformers"]

    def test_collect_requirements_scans_full_build_dir(self, tmp_path):
        """Collect requirements from Python files at build root, not only workers/."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        build_dir = project_dir / ".flash" / ".build"
        build_dir.mkdir(parents=True)

        api_example = build_dir / "api_example.py"
        api_example.write_text(
            "from runpod_flash import remote, LiveServerless\n"
            "gpu = LiveServerless()\n"
            "@remote(gpu, dependencies=['transformers'])\n"
            "async def smoke(prompt: str) -> str:\n"
            "    return prompt\n"
        )

        requirements = collect_requirements(project_dir, build_dir)

        assert "transformers" in requirements


class TestRunBuildHandlerGeneration:
    """Tests for QB handler generation in the build pipeline."""

    def _bundle_patches(self):
        """Return context manager that mocks bundling (now unconditional in run_build)."""
        from contextlib import ExitStack, contextmanager
        from pathlib import Path

        @contextmanager
        def _stack():
            with ExitStack() as stack:
                stack.enter_context(
                    patch(
                        "runpod_flash.cli.commands.build._find_runpod_flash",
                        return_value=Path("/fake/runpod_flash"),
                    )
                )
                stack.enter_context(
                    patch("runpod_flash.cli.commands.build._bundle_runpod_flash")
                )
                stack.enter_context(
                    patch(
                        "runpod_flash.cli.commands.build._remove_runpod_flash_from_requirements"
                    )
                )
                yield

        return _stack()

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
            self._bundle_patches(),
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

        with (
            patch(
                "runpod_flash.cli.commands.build.install_dependencies",
                return_value=True,
            ),
            self._bundle_patches(),
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

        with (
            patch(
                "runpod_flash.cli.commands.build.install_dependencies",
                return_value=True,
            ),
            self._bundle_patches(),
        ):
            run_build(project_dir, "test_app", no_deps=True)

        manifest_path = project_dir / ".flash" / "flash_manifest.json"
        assert manifest_path.exists()

        manifest = json.loads(manifest_path.read_text())
        for resource_name, resource_data in manifest["resources"].items():
            if not resource_data.get("is_load_balanced", False):
                assert "handler_file" in resource_data
                assert resource_data["handler_file"] == f"handler_{resource_name}.py"


class TestFindRunpodFlash:
    """Tests for _find_runpod_flash with importlib and relative path search."""

    def _create_flash_source(self, base, layout):
        """Create a minimal flash source tree under base.

        Args:
            base: Root directory (e.g., tmp_path)
            layout: 'worktree' for flash/main/src/runpod_flash,
                     'standard' for flash/src/runpod_flash

        Returns:
            Path to the created runpod_flash directory
        """
        if layout == "worktree":
            pkg = base / "flash" / "main" / "src" / "runpod_flash"
        else:
            pkg = base / "flash" / "src" / "runpod_flash"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("")
        return pkg

    @patch(
        "runpod_flash.cli.commands.build.importlib.util.find_spec", return_value=None
    )
    def test_finds_worktree_layout(self, _mock_spec, tmp_path):
        """Relative search finds flash/main/src/runpod_flash/ above project_dir."""
        expected = self._create_flash_source(tmp_path, "worktree")
        project_dir = tmp_path / "flash-examples" / "main"
        project_dir.mkdir(parents=True)

        result = _find_runpod_flash(project_dir)

        assert result == expected

    @patch(
        "runpod_flash.cli.commands.build.importlib.util.find_spec", return_value=None
    )
    def test_finds_standard_layout(self, _mock_spec, tmp_path):
        """Relative search finds flash/src/runpod_flash/ above project_dir."""
        expected = self._create_flash_source(tmp_path, "standard")
        project_dir = tmp_path / "flash-examples"
        project_dir.mkdir(parents=True)

        result = _find_runpod_flash(project_dir)

        assert result == expected

    @patch(
        "runpod_flash.cli.commands.build.importlib.util.find_spec", return_value=None
    )
    def test_returns_none_when_no_flash_repo(self, _mock_spec, tmp_path):
        """Returns None when no flash repo exists in parent chain."""
        project_dir = tmp_path / "some" / "random" / "project"
        project_dir.mkdir(parents=True)

        result = _find_runpod_flash(project_dir)

        assert result is None

    @patch(
        "runpod_flash.cli.commands.build.importlib.util.find_spec", return_value=None
    )
    def test_returns_none_when_no_project_dir(self, _mock_spec):
        """Returns None when project_dir is None."""
        result = _find_runpod_flash(None)

        assert result is None

    def test_prefers_find_spec_dev_install(self, tmp_path):
        """find_spec result is returned for dev-installed package."""
        dev_pkg = tmp_path / "dev" / "src" / "runpod_flash"
        dev_pkg.mkdir(parents=True)
        init_file = dev_pkg / "__init__.py"
        init_file.write_text("")

        mock_spec = MagicMock()
        mock_spec.origin = str(init_file)

        with patch(
            "runpod_flash.cli.commands.build.importlib.util.find_spec",
            return_value=mock_spec,
        ):
            result = _find_runpod_flash(tmp_path)

        assert result == dev_pkg

    def test_accepts_site_packages_install(self, tmp_path):
        """find_spec result from site-packages is accepted (no longer filtered)."""
        site_pkg = tmp_path / "venv" / "lib" / "site-packages" / "runpod_flash"
        site_pkg.mkdir(parents=True)
        init_file = site_pkg / "__init__.py"
        init_file.write_text("")

        mock_spec = MagicMock()
        mock_spec.origin = str(init_file)

        with patch(
            "runpod_flash.cli.commands.build.importlib.util.find_spec",
            return_value=mock_spec,
        ):
            result = _find_runpod_flash(tmp_path)

        assert result == site_pkg


class TestRunBuildBundlingFailure:
    """Tests for run_build failing when runpod_flash cannot be found."""

    def test_exits_when_runpod_flash_not_found(self, tmp_path):
        """run_build raises typer.Exit(1) when runpod_flash cannot be found."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        (project_dir / "worker.py").write_text(
            "from runpod_flash import remote, LiveServerless\n"
            "gpu = LiveServerless()\n"
            "@remote(gpu)\n"
            "def my_func(prompt: str) -> str:\n"
            "    return prompt\n"
        )

        with (
            patch(
                "runpod_flash.cli.commands.build.install_dependencies",
                return_value=True,
            ),
            patch(
                "runpod_flash.cli.commands.build._find_runpod_flash",
                return_value=None,
            ),
            pytest.raises(typer.Exit) as exc_info,
        ):
            run_build(project_dir, "test_app", no_deps=True)

        assert exc_info.value.exit_code == 1


class TestRunBuildBundling:
    """Tests for unconditional runpod_flash bundling in run_build."""

    def test_build_bundles_runpod_flash(self, tmp_path):
        """run_build bundles runpod_flash source into build directory."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        (project_dir / "worker.py").write_text(
            "from runpod_flash import remote, LiveServerless\n"
            "gpu = LiveServerless()\n"
            "@remote(gpu)\n"
            "def my_func(prompt: str) -> str:\n"
            "    return prompt\n"
        )

        # Create a fake runpod_flash package to bundle
        fake_flash = tmp_path / "fake_flash" / "runpod_flash"
        fake_flash.mkdir(parents=True)
        (fake_flash / "__init__.py").write_text("__version__ = '0.0.0-test'")

        with (
            patch(
                "runpod_flash.cli.commands.build.install_dependencies",
                return_value=True,
            ),
            patch(
                "runpod_flash.cli.commands.build._find_runpod_flash",
                return_value=fake_flash,
            ),
        ):
            run_build(project_dir, "test_app", no_deps=True)

        build_dir = project_dir / ".flash" / ".build"
        bundled = build_dir / "runpod_flash" / "__init__.py"
        assert bundled.exists()
        assert "0.0.0-test" in bundled.read_text()
