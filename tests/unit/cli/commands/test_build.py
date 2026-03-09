"""Unit tests for flash build command."""

import json
from unittest.mock import MagicMock, patch

import pytest
import typer

from runpod_flash.cli.commands.build import (
    BASE_IMAGE_PACKAGES,
    _find_runpod_flash,
    _resolve_pip_python_version,
    collect_requirements,
    create_tarball,
    extract_remote_dependencies,
    extract_package_name,
    install_dependencies,
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

    def test_extracts_dependencies_from_endpoint_qb_decorator(self, tmp_path):
        """Extract dependencies from @Endpoint(...) QB decorator."""
        workers_dir = tmp_path / "workers"
        workers_dir.mkdir()
        worker_file = workers_dir / "worker.py"

        worker_file.write_text(
            "from runpod_flash import Endpoint, GpuType\n"
            '@Endpoint(name="gpu_worker", gpu=GpuType.ANY, dependencies=["torch"])\n'
            "async def process(data: dict) -> dict:\n"
            "    return data\n"
        )

        dependencies = extract_remote_dependencies(workers_dir)

        assert dependencies == ["torch"]

    def test_extracts_dependencies_from_endpoint_variable_assignment(self, tmp_path):
        """Extract dependencies from ep = Endpoint(dependencies=[...]) LB pattern."""
        workers_dir = tmp_path / "workers"
        workers_dir.mkdir()
        worker_file = workers_dir / "worker.py"

        worker_file.write_text(
            "from runpod_flash import Endpoint, GpuGroup\n"
            'api = Endpoint(name="my-api", gpu=GpuGroup.ADA_24, dependencies=["numpy", "pandas"])\n'
            "\n"
            '@api.post("/compute")\n'
            "async def compute(request: dict) -> dict:\n"
            "    return request\n"
        )

        dependencies = extract_remote_dependencies(workers_dir)

        assert sorted(dependencies) == ["numpy", "pandas"]

    def test_extracts_dependencies_from_mixed_patterns(self, tmp_path):
        """Extract dependencies from both @remote and Endpoint patterns."""
        workers_dir = tmp_path / "workers"
        workers_dir.mkdir()

        # file with @remote
        f1 = workers_dir / "remote_worker.py"
        f1.write_text(
            "from runpod_flash import remote, LiveServerless\n"
            "gpu = LiveServerless()\n"
            "@remote(gpu, dependencies=['torch'])\n"
            "async def train(data): return data\n"
        )

        # file with @Endpoint QB
        f2 = workers_dir / "endpoint_worker.py"
        f2.write_text(
            "from runpod_flash import Endpoint\n"
            '@Endpoint(name="w", dependencies=["numpy"])\n'
            "async def infer(data): return data\n"
        )

        # file with Endpoint LB variable
        f3 = workers_dir / "lb_worker.py"
        f3.write_text(
            "from runpod_flash import Endpoint\n"
            'api = Endpoint(name="api", dependencies=["fastapi"])\n'
            '@api.get("/health")\n'
            "async def health(): return {}\n"
        )

        dependencies = extract_remote_dependencies(workers_dir)

        assert sorted(dependencies) == ["fastapi", "numpy", "torch"]


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


class TestBaseImageAutoExclusion:
    """Tests for automatic exclusion of base image packages (torch, etc.)."""

    def _bundle_patches(self):
        """Return context manager that mocks bundling."""
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

    def test_constant_contains_expected_packages(self):
        """Verify torch ecosystem, numpy, and triton are in BASE_IMAGE_PACKAGES."""
        assert "torch" in BASE_IMAGE_PACKAGES
        assert "torchvision" in BASE_IMAGE_PACKAGES
        assert "torchaudio" in BASE_IMAGE_PACKAGES
        assert "numpy" in BASE_IMAGE_PACKAGES
        assert "triton" in BASE_IMAGE_PACKAGES

    def test_auto_excludes_torch_without_flag(self, tmp_path):
        """Torch and numpy are filtered even with no --exclude flag."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        (project_dir / "worker.py").write_text(
            "from runpod_flash import remote, LiveServerless\n"
            "gpu = LiveServerless()\n"
            "@remote(gpu, dependencies=['torch', 'numpy', 'requests'])\n"
            "def my_func(prompt: str) -> str:\n"
            "    return prompt\n"
        )

        installed = []

        def fake_install(_build_dir, reqs, _no_deps, target_python_version=None):
            installed.extend(reqs)
            return True

        with (
            patch(
                "runpod_flash.cli.commands.build.install_dependencies",
                side_effect=fake_install,
            ),
            self._bundle_patches(),
        ):
            run_build(project_dir, "test_app", no_deps=True)

        pkg_names = [extract_package_name(r) for r in installed]
        assert "torch" not in pkg_names
        assert "numpy" not in pkg_names
        assert "requests" in pkg_names

    def test_user_excludes_merged_with_auto(self, tmp_path):
        """User --exclude scipy + auto torch/numpy = all excluded."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        (project_dir / "worker.py").write_text(
            "from runpod_flash import remote, LiveServerless\n"
            "gpu = LiveServerless()\n"
            "@remote(gpu, dependencies=['torch', 'numpy', 'scipy', 'pandas'])\n"
            "def my_func(prompt: str) -> str:\n"
            "    return prompt\n"
        )

        installed = []

        def fake_install(_build_dir, reqs, _no_deps, target_python_version=None):
            installed.extend(reqs)
            return True

        with (
            patch(
                "runpod_flash.cli.commands.build.install_dependencies",
                side_effect=fake_install,
            ),
            self._bundle_patches(),
        ):
            run_build(project_dir, "test_app", no_deps=True, exclude="scipy")

        pkg_names = [extract_package_name(r) for r in installed]
        assert "torch" not in pkg_names
        assert "numpy" not in pkg_names
        assert "scipy" not in pkg_names
        assert "pandas" in pkg_names

    def test_auto_exclude_silent_when_not_in_requirements(self, tmp_path, capsys):
        """No auto-exclude message if no base image packages are in requirements."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        (project_dir / "worker.py").write_text(
            "from runpod_flash import remote, LiveServerless\n"
            "gpu = LiveServerless()\n"
            "@remote(gpu, dependencies=['requests'])\n"
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

        captured = capsys.readouterr()
        assert "Auto-excluded base image packages" not in captured.out

    def test_user_unmatched_warning_excludes_base_image_packages(
        self, tmp_path, capsys
    ):
        """--exclude torch doesn't warn 'no match' when torch isn't in requirements."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        (project_dir / "worker.py").write_text(
            "from runpod_flash import remote, LiveServerless\n"
            "gpu = LiveServerless()\n"
            "@remote(gpu, dependencies=['requests'])\n"
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
            run_build(project_dir, "test_app", no_deps=True, exclude="torch")

        captured = capsys.readouterr()
        assert "No packages matched exclusions" not in captured.out

    def test_tarball_excludes_base_image_packages(self, tmp_path):
        """create_tarball filters out excluded package directories and dist-info."""
        build_dir = tmp_path / "build"
        build_dir.mkdir()

        # Create fake package directories
        (build_dir / "torch" / "nn").mkdir(parents=True)
        (build_dir / "torch" / "__init__.py").write_text("")
        (build_dir / "numpy").mkdir()
        (build_dir / "numpy" / "__init__.py").write_text("")
        (build_dir / "torch-2.0.0.dist-info").mkdir()
        (build_dir / "torch-2.0.0.dist-info" / "METADATA").write_text("")
        (build_dir / "requests").mkdir()
        (build_dir / "requests" / "__init__.py").write_text("")

        output = tmp_path / "test.tar.gz"
        create_tarball(
            build_dir, output, "test_app", excluded_packages=["torch", "numpy"]
        )

        import tarfile

        with tarfile.open(output, "r:gz") as tar:
            names = tar.getnames()

        # torch and numpy directories (and dist-info) should be excluded
        torch_entries = [n for n in names if "torch" in n]
        numpy_entries = [n for n in names if "numpy" in n]
        assert torch_entries == [], f"torch entries found: {torch_entries}"
        assert numpy_entries == [], f"numpy entries found: {numpy_entries}"
        # requests should still be present
        assert any("requests" in n for n in names)

    def test_tarball_keeps_non_excluded_packages(self, tmp_path):
        """create_tarball keeps packages not in the exclusion list."""
        build_dir = tmp_path / "build"
        build_dir.mkdir()

        (build_dir / "requests").mkdir()
        (build_dir / "requests" / "__init__.py").write_text("")
        (build_dir / "my_torch_utils").mkdir()
        (build_dir / "my_torch_utils" / "__init__.py").write_text("")

        output = tmp_path / "test.tar.gz"
        create_tarball(build_dir, output, "test_app", excluded_packages=["torch"])

        import tarfile

        with tarfile.open(output, "r:gz") as tar:
            names = tar.getnames()

        assert any("requests" in n for n in names)
        # my_torch_utils should NOT be excluded (exact match, not substring)
        assert any("my_torch_utils" in n for n in names)


class TestResolvePipPythonVersion:
    """Tests for _resolve_pip_python_version."""

    def test_returns_version_from_gpu_manifest(self):
        """Returns target_python_version from GPU-containing manifest."""
        manifest = {
            "resources": {
                "gpu_worker": {
                    "resource_type": "LiveServerless",
                    "target_python_version": "3.12",
                },
            }
        }
        assert _resolve_pip_python_version(manifest) == "3.12"

    def test_returns_none_for_empty_resources(self):
        """Returns None when no resources have target_python_version."""
        manifest = {"resources": {}}
        assert _resolve_pip_python_version(manifest) is None

    def test_returns_none_for_missing_field(self):
        """Returns None when resources lack target_python_version."""
        manifest = {
            "resources": {
                "worker": {"resource_type": "LiveServerless"},
            }
        }
        assert _resolve_pip_python_version(manifest) is None

    def test_consistent_versions_returns_single(self):
        """Returns the version when all resources agree."""
        manifest = {
            "resources": {
                "gpu": {"target_python_version": "3.12"},
                "cpu": {"target_python_version": "3.12"},
            }
        }
        assert _resolve_pip_python_version(manifest) == "3.12"

    def test_mixed_versions_returns_highest(self):
        """Returns the highest version when resources disagree."""
        manifest = {
            "resources": {
                "gpu": {"target_python_version": "3.12"},
                "cpu": {"target_python_version": "3.11"},
            }
        }
        assert _resolve_pip_python_version(manifest) == "3.12"


class TestInstallDependenciesTargetVersion:
    """Tests for install_dependencies with target_python_version."""

    def test_uses_target_version_for_python_version_flag(self, tmp_path):
        """install_dependencies passes target version to --python-version."""
        build_dir = tmp_path / "build"
        build_dir.mkdir()

        captured_cmd = []

        def mock_run(cmd, **kwargs):
            captured_cmd.extend(cmd)
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""
            return result

        with patch("subprocess.run", side_effect=mock_run):
            install_dependencies(
                build_dir,
                ["requests"],
                no_deps=False,
                target_python_version="3.12",
            )

        # Find --python-version in the captured command
        for i, arg in enumerate(captured_cmd):
            if arg == "--python-version" and i + 1 < len(captured_cmd):
                assert captured_cmd[i + 1] == "3.12"
                break
        else:
            pytest.fail("--python-version not found in pip command")
