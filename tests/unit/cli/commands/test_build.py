"""Unit tests for flash build command."""

import json
from unittest.mock import MagicMock, patch

import pytest
import typer

from runpod_flash.cli.commands.build import (
    SIZE_PROHIBITIVE_PACKAGES,
    _requirement_name,
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

    def test_package_with_compatible_release_and_direct_reference(self):
        """'~=' pins, 'name @ url' references, and old-style parens split off."""
        assert extract_package_name("sympy~=1.14") == "sympy"
        assert extract_package_name("sympy @ https://example.com/s.whl") == "sympy"
        assert extract_package_name("foo (>=1.0)") == "foo"

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
            "gpu = LiveServerless(name='gpu_worker')\n"
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
            "gpu = LiveServerless(name='gpu_worker')\n"
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
            "gpu = LiveServerless(name='gpu_worker')\n"
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
            "gpu = LiveServerless(name='gpu_worker')\n"
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
            "gpu = LiveServerless(name='gpu_worker')\n"
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
            "gpu = LiveServerless(name='gpu_worker')\n"
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
            "gpu = LiveServerless(name='gpu_worker')\n"
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
            "gpu = LiveServerless(name='gpu_worker')\n"
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
        """Verify CUDA/torch ecosystem packages are in SIZE_PROHIBITIVE_PACKAGES."""
        assert "torch" in SIZE_PROHIBITIVE_PACKAGES
        assert "torchvision" in SIZE_PROHIBITIVE_PACKAGES
        assert "torchaudio" in SIZE_PROHIBITIVE_PACKAGES
        assert "triton" in SIZE_PROHIBITIVE_PACKAGES

    def test_numpy_not_in_size_prohibitive_packages(self):
        """NumPy must NOT be excluded — CPU images (python-slim) don't ship it."""
        assert "numpy" not in SIZE_PROHIBITIVE_PACKAGES

    def test_auto_excludes_torch_without_flag(self, tmp_path):
        """Torch is filtered even with no --exclude flag; numpy passes through."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        (project_dir / "worker.py").write_text(
            "from runpod_flash import remote, LiveServerless\n"
            "gpu = LiveServerless(name='gpu_worker')\n"
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
        assert "numpy" in pkg_names
        assert "requests" in pkg_names

    def test_user_excludes_merged_with_auto(self, tmp_path):
        """User --exclude scipy + auto torch = all excluded; numpy passes through."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        (project_dir / "worker.py").write_text(
            "from runpod_flash import remote, LiveServerless\n"
            "gpu = LiveServerless(name='gpu_worker')\n"
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
        assert "numpy" in pkg_names
        assert "scipy" not in pkg_names
        assert "pandas" in pkg_names

    def test_auto_exclude_silent_when_not_in_requirements(self, tmp_path, capsys):
        """No auto-exclude message if no size-prohibitive packages are in requirements."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        (project_dir / "worker.py").write_text(
            "from runpod_flash import remote, LiveServerless\n"
            "gpu = LiveServerless(name='gpu_worker')\n"
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
        assert "not bundling" not in captured.out

    def _build_with_deps(self, tmp_path, deps, exclude=None):
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        (project_dir / "worker.py").write_text(
            "from runpod_flash import remote, LiveServerless\n"
            "gpu = LiveServerless(name='gpu_worker')\n"
            f"@remote(gpu, dependencies={deps!r})\n"
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
            run_build(project_dir, "test_app", no_deps=True, exclude=exclude)

        return [extract_package_name(r) for r in installed]

    @pytest.mark.parametrize(
        "pinned",
        [
            "torchvision~=0.24.1",
            "torchvision @ https://example.com/torchvision.whl",
            "https://download.pytorch.org/whl/cu128/"
            "torchvision-0.24.1%2Bcu128-cp312-cp312-manylinux_2_28_x86_64.whl",
        ],
    )
    def test_auto_exclude_catches_compatible_and_url_pins(
        self, tmp_path, capsys, pinned
    ):
        """'~=' and 'name @ url' torch-family requirements are excluded and warned."""
        pkg_names = self._build_with_deps(tmp_path, [pinned, "requests"])

        out = capsys.readouterr().out
        assert not any("torchvision" in name for name in pkg_names)
        assert "requests" in pkg_names
        assert "Version pins ignored" in out

    @pytest.mark.parametrize(
        "requirement", ["sympy~=1.14", "sympy @ https://example.com/sympy.whl"]
    )
    def test_user_exclude_matches_compatible_and_url_pins(
        self, tmp_path, capsys, requirement
    ):
        """--exclude sympy also catches 'sympy~=1.14' and 'sympy @ url'."""
        pkg_names = self._build_with_deps(
            tmp_path, [requirement, "requests"], exclude="sympy"
        )

        out = capsys.readouterr().out
        assert "sympy" not in pkg_names
        assert "requests" in pkg_names
        assert "No packages matched exclusions" not in out

    def test_auto_exclude_tells_user_image_provides_package(self, tmp_path, capsys):
        """An unpinned torchvision is dropped with a visible notice, not a warning."""
        pkg_names = self._build_with_deps(tmp_path, ["torchvision", "requests"])

        out = capsys.readouterr().out
        assert "torchvision" not in pkg_names
        assert "not bundling torchvision" in out
        assert "worker image" in out
        assert "Version pins ignored" not in out

    def test_auto_exclude_warns_when_version_pin_is_ignored(self, tmp_path, capsys):
        """A pinned torch-family requirement warns that the pin has no effect."""
        pkg_names = self._build_with_deps(
            tmp_path, ["torchvision==0.29.1", "torch", "requests"]
        )

        out = capsys.readouterr().out
        assert "torchvision" not in pkg_names
        assert "torch" not in pkg_names
        assert "Version pins ignored" in out
        assert "torchvision==0.29.1" in out

    def test_user_unmatched_warning_excludes_base_image_packages(
        self, tmp_path, capsys
    ):
        """--exclude torch doesn't warn 'no match' when torch isn't in requirements."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        (project_dir / "worker.py").write_text(
            "from runpod_flash import remote, LiveServerless\n"
            "gpu = LiveServerless(name='gpu_worker')\n"
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

    def _fake_wheel(self, build_dir, dist_info, files, requires=(), metadata=True):
        (build_dir / dist_info).mkdir()
        for f in files:
            path = build_dir / f
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("")
        if metadata:
            lines = ["Metadata-Version: 2.1", f"Name: {dist_info.split('-')[0]}"]
            lines += [f"Requires-Dist: {r}" for r in requires]
            (build_dir / dist_info / "METADATA").write_text("\n".join(lines) + "\n")
        record = [f"{f},," for f in files] + [f"{dist_info}/RECORD,,"]
        (build_dir / dist_info / "RECORD").write_text("\n".join(record))

    def _tarball_names(self, tmp_path, build_dir, roots):
        import tarfile

        output = tmp_path / "test.tar.gz"
        create_tarball(
            build_dir,
            output,
            "test_app",
            excluded_packages=sorted(SIZE_PROHIBITIVE_PACKAGES),
            root_requirements=roots,
        )
        with tarfile.open(output, "r:gz") as tar:
            return {n.removeprefix("./") for n in tar.getnames() if n != "."}

    def _tarball_top_level(self, tmp_path, build_dir, roots):
        names = self._tarball_names(tmp_path, build_dir, roots)
        return {n.split("/")[0] for n in names}

    def _torch_tree(self, build_dir, nvidia_metadata=True):
        wheel = self._fake_wheel
        wheel(
            build_dir,
            "torch-2.14.1.dist-info",
            ["torch/__init__.py"],
            ["filelock", "nvidia-cublas==13.1.1.3; platform_system == 'Linux'"],
        )
        wheel(
            build_dir,
            "torchvision-0.29.1.dist-info",
            ["torchvision/__init__.py"],
            ["torch==2.14.1", "numpy", "pillow>=5.3.0"],
        )
        wheel(
            build_dir,
            "nvidia_cublas-13.1.1.3.dist-info",
            ["nvidia/cublas/lib.so"],
            metadata=nvidia_metadata,
        )
        wheel(build_dir, "numpy-2.4.6.dist-info", ["numpy/__init__.py"])
        wheel(build_dir, "pillow-12.3.0.dist-info", ["PIL/__init__.py"])
        wheel(build_dir, "filelock-4.2.0.dist-info", ["filelock/__init__.py"])
        wheel(
            build_dir,
            "huggingface_hub-2.2.0.dist-info",
            ["huggingface_hub/__init__.py"],
            ["filelock"],
        )
        wheel(
            build_dir,
            "timm-1.0.30.dist-info",
            ["timm/__init__.py"],
            ["torch", "torchvision", "huggingface_hub"],
        )

    def test_tarball_excludes_extra_top_level_dirs_of_excluded_wheels(self, tmp_path):
        """Top-level dirs listed in an excluded wheel's RECORD are dropped too,
        but a dir shared with a kept wheel (bin/) stays."""
        build_dir = tmp_path / "build"
        build_dir.mkdir()
        wheel = self._fake_wheel
        wheel(
            build_dir,
            "torch-2.14.1.dist-info",
            ["torch/__init__.py", "functorch/__init__.py", "bin/torchrun"],
        )
        wheel(
            build_dir,
            "torchvision-0.29.1.dist-info",
            ["torchvision/__init__.py", "torchvision.libs/libpng.so"],
            ["torch"],
        )
        wheel(
            build_dir,
            "timm-1.0.30.dist-info",
            ["timm/__init__.py", "bin/timm-cli"],
            ["torch", "torchvision"],
        )

        top_level = self._tarball_top_level(tmp_path, build_dir, ["timm"])

        assert top_level == {"timm", "timm-1.0.30.dist-info", "bin"}

    def test_tarball_drops_wheels_only_torch_family_needs(self, tmp_path):
        """nvidia/numpy pulled in only by torch/torchvision are dropped; deps of
        kept wheels (filelock) and root requirements (pillow) stay."""
        build_dir = tmp_path / "build"
        build_dir.mkdir()
        self._torch_tree(build_dir)

        top_level = self._tarball_top_level(tmp_path, build_dir, ["timm", "pillow>=10"])

        packages = {t for t in top_level if not t.endswith(".dist-info")}
        assert packages == {"timm", "huggingface_hub", "filelock", "PIL"}

    def test_tarball_keeps_dependencies_when_metadata_missing(self, tmp_path):
        """Without full metadata the dependency graph is unknown, so only the
        excluded packages themselves are dropped."""
        build_dir = tmp_path / "build"
        build_dir.mkdir()
        self._torch_tree(build_dir, nvidia_metadata=False)

        top_level = self._tarball_top_level(tmp_path, build_dir, ["timm"])

        assert "nvidia" in top_level
        assert "numpy" in top_level
        assert "torch" not in top_level
        assert "torchvision" not in top_level

    def test_tarball_keeps_root_requirement_given_as_direct_url(self, tmp_path):
        """A root written as 'name @ url' still protects that wheel."""
        build_dir = tmp_path / "build"
        build_dir.mkdir()
        self._torch_tree(build_dir)

        top_level = self._tarball_top_level(
            tmp_path, build_dir, ["timm", "numpy @ https://example.com/numpy.whl"]
        )

        assert "numpy" in top_level

    def test_tarball_filters_files_in_dir_shared_with_kept_wheel(self, tmp_path):
        """A kept nvidia wheel keeps its files under nvidia/, but files from an
        nvidia wheel only torch needs are still dropped."""
        build_dir = tmp_path / "build"
        build_dir.mkdir()
        self._torch_tree(build_dir)
        self._fake_wheel(
            build_dir, "nvidia_cudnn-9.24.0.dist-info", ["nvidia/cudnn/lib.so"]
        )

        names = self._tarball_names(tmp_path, build_dir, ["timm", "nvidia-cudnn"])

        assert "nvidia/cudnn/lib.so" in names
        assert "nvidia/cublas/lib.so" not in names
        assert not any(n.startswith("nvidia_cublas") for n in names)

    def test_tarball_drops_only_excluded_when_a_record_is_missing(self, tmp_path):
        """Without every RECORD, file ownership is unknown, so only the
        excluded packages themselves are dropped."""
        build_dir = tmp_path / "build"
        build_dir.mkdir()
        self._torch_tree(build_dir)
        (build_dir / "huggingface_hub-2.2.0.dist-info" / "RECORD").unlink()

        top_level = self._tarball_top_level(tmp_path, build_dir, ["timm"])

        assert {"nvidia", "numpy", "huggingface_hub"} <= top_level
        assert "torch" not in top_level
        assert "torchvision" not in top_level

    def test_tarball_keeps_dependencies_of_user_excluded_package(self, tmp_path):
        """--exclude drops only the named package. The worker image doesn't
        provide its dependencies, so they stay."""
        import tarfile

        build_dir = tmp_path / "build"
        build_dir.mkdir()
        self._fake_wheel(
            build_dir, "scipy-1.17.0.dist-info", ["scipy/__init__.py"], ["numpy"]
        )
        self._fake_wheel(build_dir, "numpy-2.4.6.dist-info", ["numpy/__init__.py"])

        output = tmp_path / "test.tar.gz"
        create_tarball(
            build_dir,
            output,
            "test_app",
            excluded_packages=sorted(SIZE_PROHIBITIVE_PACKAGES | {"scipy"}),
            root_requirements=["scipy"],
        )
        with tarfile.open(output, "r:gz") as tar:
            top_level = {n.split("/")[1] for n in tar.getnames() if n != "."}

        assert "scipy" not in top_level
        assert "numpy" in top_level

    def test_tarball_skips_pruning_when_a_requirement_has_no_name(self, tmp_path):
        """A bare URL could install any wheel, so nothing beyond the excluded
        packages is dropped."""
        build_dir = tmp_path / "build"
        build_dir.mkdir()
        self._torch_tree(build_dir)

        top_level = self._tarball_top_level(
            tmp_path, build_dir, ["timm", "https://example.com/numpy.whl"]
        )

        assert {"numpy", "nvidia"} <= top_level
        assert "torch" not in top_level

    def test_tarball_skips_pruning_on_unreadable_requires_dist(self, tmp_path):
        """A Requires-Dist line without a name stops dependency pruning."""
        build_dir = tmp_path / "build"
        build_dir.mkdir()
        self._torch_tree(build_dir)
        metadata = build_dir / "timm-1.0.30.dist-info" / "METADATA"
        metadata.write_text(metadata.read_text() + "Requires-Dist: ./vendored.whl\n")

        top_level = self._tarball_top_level(tmp_path, build_dir, ["timm"])

        assert {"numpy", "nvidia"} <= top_level
        assert "torch" not in top_level

    def test_tarball_skips_pruning_for_bare_wheel_filename(self, tmp_path):
        """A wheel filename root names no distribution, so pruning is skipped."""
        build_dir = tmp_path / "build"
        build_dir.mkdir()
        self._torch_tree(build_dir)

        top_level = self._tarball_top_level(
            tmp_path,
            build_dir,
            ["timm", "numpy-2.4.6-cp312-cp312-manylinux_2_28_x86_64.whl"],
        )

        assert "numpy" in top_level

    def test_tarball_keeps_dependencies_of_user_excluded_torch_dependency(
        self, tmp_path
    ):
        """--exclude sympy drops sympy only, even though torch also needs it."""
        import tarfile

        build_dir = tmp_path / "build"
        build_dir.mkdir()
        wheel = self._fake_wheel
        wheel(build_dir, "torch-2.14.1.dist-info", ["torch/__init__.py"], ["sympy"])
        wheel(build_dir, "sympy-1.14.0.dist-info", ["sympy/__init__.py"], ["mpmath"])
        wheel(build_dir, "mpmath-1.3.0.dist-info", ["mpmath/__init__.py"])
        wheel(build_dir, "timm-1.0.30.dist-info", ["timm/__init__.py"], ["torch"])

        output = tmp_path / "test.tar.gz"
        create_tarball(
            build_dir,
            output,
            "test_app",
            excluded_packages=sorted(SIZE_PROHIBITIVE_PACKAGES | {"sympy"}),
            root_requirements=["timm"],
        )
        with tarfile.open(output, "r:gz") as tar:
            top_level = {n.split("/")[1] for n in tar.getnames() if n != "."}

        assert "sympy" not in top_level
        assert "mpmath" in top_level

    def test_tarball_keeps_unrecorded_files_next_to_dropped_ones(self, tmp_path):
        """Files no RECORD lists stay, even beside files of a dropped wheel."""
        build_dir = tmp_path / "build"
        build_dir.mkdir()
        self._torch_tree(build_dir)
        (build_dir / "nvidia" / "notes.txt").write_text("")

        names = self._tarball_names(tmp_path, build_dir, ["timm"])

        assert "nvidia/notes.txt" in names
        assert "nvidia/cublas/lib.so" not in names

    def test_tarball_normalizes_record_paths(self, tmp_path):
        """RECORD paths written with ./ or backslashes still match on disk."""
        build_dir = tmp_path / "build"
        build_dir.mkdir()
        self._torch_tree(build_dir)
        (build_dir / "nvidia_cublas-13.1.1.3.dist-info" / "RECORD").write_text(
            "./nvidia\\cublas\\lib.so,,\n"
        )

        names = self._tarball_names(tmp_path, build_dir, ["timm"])

        assert "nvidia/cublas/lib.so" not in names

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
                "cpu": {"target_python_version": "3.12"},
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


class TestComputeSourceFingerprint:
    """Tests for compute_source_fingerprint function."""

    def test_deterministic_output(self, tmp_path):
        """Same files produce same hash across calls."""
        from runpod_flash.cli.commands.build import compute_source_fingerprint

        f1 = tmp_path / "app.py"
        f1.write_text("print('hello')")
        f2 = tmp_path / "utils.py"
        f2.write_text("x = 1")

        files = [f1, f2]
        hash1 = compute_source_fingerprint(tmp_path, files)
        hash2 = compute_source_fingerprint(tmp_path, files)
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA-256 hex digest length

    def test_content_sensitive(self, tmp_path):
        """Changing file content changes the hash."""
        from runpod_flash.cli.commands.build import compute_source_fingerprint

        f1 = tmp_path / "app.py"
        f1.write_text("print('hello')")
        hash1 = compute_source_fingerprint(tmp_path, [f1])

        f1.write_text("print('world')")
        hash2 = compute_source_fingerprint(tmp_path, [f1])
        assert hash1 != hash2

    def test_path_sensitive(self, tmp_path):
        """Renaming a file (same content) changes the hash."""
        from runpod_flash.cli.commands.build import compute_source_fingerprint

        f1 = tmp_path / "app.py"
        f1.write_text("content")
        hash1 = compute_source_fingerprint(tmp_path, [f1])

        f2 = tmp_path / "main.py"
        f2.write_text("content")
        hash2 = compute_source_fingerprint(tmp_path, [f2])
        assert hash1 != hash2

    def test_order_independent(self, tmp_path):
        """Shuffled input order produces same hash (function sorts internally)."""
        from runpod_flash.cli.commands.build import compute_source_fingerprint

        f1 = tmp_path / "a.py"
        f1.write_text("aaa")
        f2 = tmp_path / "b.py"
        f2.write_text("bbb")

        hash1 = compute_source_fingerprint(tmp_path, [f1, f2])
        hash2 = compute_source_fingerprint(tmp_path, [f2, f1])
        assert hash1 == hash2

    def test_empty_file_list(self, tmp_path):
        """Empty file list returns a valid SHA-256 hash."""
        from runpod_flash.cli.commands.build import compute_source_fingerprint

        result = compute_source_fingerprint(tmp_path, [])
        assert len(result) == 64

    def test_handles_binary_files(self, tmp_path):
        """Binary files are hashed without error."""
        from runpod_flash.cli.commands.build import compute_source_fingerprint

        f1 = tmp_path / "data.bin"
        f1.write_bytes(b"\x00\x01\x02\xff")
        result = compute_source_fingerprint(tmp_path, [f1])
        assert len(result) == 64


@pytest.mark.parametrize(
    ("requirement", "expected"),
    [
        ("torch", "torch"),
        ("Pillow[extra] >= 5", "pillow"),
        ("zope.interface", "zope_interface"),
        ("filelock @ https://example.com/filelock.whl", "filelock"),
        ("nvidia-cublas==13.1; platform_system == 'Linux'", "nvidia_cublas"),
        ("foo (>=1.0)", "foo"),
        ("https://example.com/numpy.whl", ""),
        ("./wheels/numpy.whl", ""),
        ("-r other.txt", ""),
        ("numpy-2.4.6-cp312-cp312-manylinux_2_28_x86_64.whl", ""),
        ("mypkg-1.0.tar.gz", ""),
        ("my.whl==1.0", "my_whl"),
    ],
)
def test_requirement_name(requirement, expected):
    assert _requirement_name(requirement) == expected
