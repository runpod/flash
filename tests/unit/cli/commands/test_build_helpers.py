"""Tests for build.py helper functions: _bundle_runpod_flash,
_remove_runpod_flash_from_requirements, _extract_runpod_flash_dependencies.

These functions are always mocked in existing build tests; these tests
exercise them directly.
"""

from runpod_flash.cli.commands.build import (
    _bundle_runpod_flash,
    _extract_runpod_flash_dependencies,
    _find_runpod_flash,
    _remove_runpod_flash_from_requirements,
)


class TestBundleRunpodFlash:
    """Direct tests for _bundle_runpod_flash."""

    def test_copies_package_to_build_dir(self, tmp_path):
        """Bundle creates a runpod_flash directory in build_dir."""
        flash_pkg = tmp_path / "source" / "runpod_flash"
        flash_pkg.mkdir(parents=True)
        (flash_pkg / "__init__.py").write_text("__version__ = '0.0.0-test'")
        (flash_pkg / "client.py").write_text("# client code")

        build_dir = tmp_path / "build"
        build_dir.mkdir()

        _bundle_runpod_flash(build_dir, flash_pkg)

        bundled = build_dir / "runpod_flash"
        assert bundled.is_dir()
        assert (bundled / "__init__.py").exists()
        assert "0.0.0-test" in (bundled / "__init__.py").read_text()
        assert (bundled / "client.py").exists()

    def test_removes_existing_destination(self, tmp_path):
        """Bundle removes existing runpod_flash dir before copying."""
        flash_pkg = tmp_path / "source" / "runpod_flash"
        flash_pkg.mkdir(parents=True)
        (flash_pkg / "__init__.py").write_text("__version__ = 'new'")

        build_dir = tmp_path / "build"
        build_dir.mkdir()

        # Pre-existing stale directory
        old = build_dir / "runpod_flash"
        old.mkdir()
        (old / "stale_file.py").write_text("# should be removed")

        _bundle_runpod_flash(build_dir, flash_pkg)

        bundled = build_dir / "runpod_flash"
        assert not (bundled / "stale_file.py").exists()
        assert "new" in (bundled / "__init__.py").read_text()

    def test_ignores_pycache_and_pyc(self, tmp_path):
        """Bundle excludes __pycache__ and *.pyc files."""
        flash_pkg = tmp_path / "source" / "runpod_flash"
        flash_pkg.mkdir(parents=True)
        (flash_pkg / "__init__.py").write_text("")

        pycache = flash_pkg / "__pycache__"
        pycache.mkdir()
        (pycache / "module.cpython-311.pyc").write_text("")

        (flash_pkg / "compiled.pyc").write_text("")

        build_dir = tmp_path / "build"
        build_dir.mkdir()

        _bundle_runpod_flash(build_dir, flash_pkg)

        bundled = build_dir / "runpod_flash"
        assert not (bundled / "__pycache__").exists()
        assert not (bundled / "compiled.pyc").exists()

    def test_copies_nested_subdirectories(self, tmp_path):
        """Bundle preserves nested package structure."""
        flash_pkg = tmp_path / "source" / "runpod_flash"
        flash_pkg.mkdir(parents=True)
        (flash_pkg / "__init__.py").write_text("")

        sub = flash_pkg / "core" / "api"
        sub.mkdir(parents=True)
        (sub / "__init__.py").write_text("")
        (sub / "runpod.py").write_text("# api code")

        build_dir = tmp_path / "build"
        build_dir.mkdir()

        _bundle_runpod_flash(build_dir, flash_pkg)

        assert (build_dir / "runpod_flash" / "core" / "api" / "runpod.py").exists()


class TestRemoveRunpodFlashFromRequirements:
    """Direct tests for _remove_runpod_flash_from_requirements."""

    def test_removes_runpod_flash_with_underscore(self, tmp_path):
        """Filters runpod_flash entries (underscore form)."""
        req = tmp_path / "requirements.txt"
        req.write_text("runpod_flash==1.4.0\nnumpy>=1.24\n")

        _remove_runpod_flash_from_requirements(tmp_path)

        lines = req.read_text().strip().splitlines()
        assert len(lines) == 1
        assert "numpy" in lines[0]

    def test_removes_runpod_flash_with_hyphen(self, tmp_path):
        """Filters runpod-flash entries (hyphen form)."""
        req = tmp_path / "requirements.txt"
        req.write_text("runpod-flash>=1.0\nrequests\n")

        _remove_runpod_flash_from_requirements(tmp_path)

        lines = req.read_text().strip().splitlines()
        assert len(lines) == 1
        assert "requests" in lines[0]

    def test_case_insensitive_filtering(self, tmp_path):
        """Filters regardless of casing."""
        req = tmp_path / "requirements.txt"
        req.write_text("Runpod_Flash==1.0\nRUNPOD-FLASH>=2.0\npandas\n")

        _remove_runpod_flash_from_requirements(tmp_path)

        lines = req.read_text().strip().splitlines()
        assert len(lines) == 1
        assert "pandas" in lines[0]

    def test_no_requirements_file(self, tmp_path):
        """Does nothing if requirements.txt doesn't exist."""
        _remove_runpod_flash_from_requirements(tmp_path)
        # Should not raise

    def test_removes_dist_info(self, tmp_path):
        """Cleans up runpod_flash dist-info directories."""
        req = tmp_path / "requirements.txt"
        req.write_text("numpy\n")

        dist_info = tmp_path / "runpod_flash-1.4.0.dist-info"
        dist_info.mkdir()
        (dist_info / "METADATA").write_text("Name: runpod-flash")

        _remove_runpod_flash_from_requirements(tmp_path)

        assert not dist_info.exists()

    def test_keeps_other_packages(self, tmp_path):
        """Keeps packages that just start with 'runpod' but aren't runpod_flash."""
        req = tmp_path / "requirements.txt"
        req.write_text("runpod>=1.0\nrunpod_flash==1.4.0\naiohttp\n")

        _remove_runpod_flash_from_requirements(tmp_path)

        lines = req.read_text().strip().splitlines()
        assert len(lines) == 2
        assert any("runpod" in line and "flash" not in line for line in lines)
        assert any("aiohttp" in line for line in lines)


class TestExtractRunpodFlashDependencies:
    """Direct tests for _extract_runpod_flash_dependencies."""

    def test_extracts_dependencies_from_pyproject(self, tmp_path):
        """Extracts [project.dependencies] from pyproject.toml."""
        # Create flash_pkg_dir at src/runpod_flash
        pkg_dir = tmp_path / "src" / "runpod_flash"
        pkg_dir.mkdir(parents=True)

        # pyproject.toml is at project root (2 levels up from pkg_dir)
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[project]\nname = "runpod-flash"\n'
            'dependencies = ["cloudpickle>=3.0", "pydantic>=2.0", "rich>=14.0"]\n'
        )

        deps = _extract_runpod_flash_dependencies(pkg_dir)

        assert len(deps) == 3
        assert "cloudpickle>=3.0" in deps
        assert "pydantic>=2.0" in deps
        assert "rich>=14.0" in deps

    def test_returns_empty_when_no_pyproject(self, tmp_path):
        """Returns empty list when pyproject.toml doesn't exist."""
        pkg_dir = tmp_path / "src" / "runpod_flash"
        pkg_dir.mkdir(parents=True)

        deps = _extract_runpod_flash_dependencies(pkg_dir)
        assert deps == []

    def test_returns_empty_on_parse_error(self, tmp_path):
        """Returns empty list when pyproject.toml is invalid."""
        pkg_dir = tmp_path / "src" / "runpod_flash"
        pkg_dir.mkdir(parents=True)

        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("this is not valid toml {{{{")

        deps = _extract_runpod_flash_dependencies(pkg_dir)
        assert deps == []

    def test_returns_empty_when_no_dependencies_key(self, tmp_path):
        """Returns empty list when [project.dependencies] is missing."""
        pkg_dir = tmp_path / "src" / "runpod_flash"
        pkg_dir.mkdir(parents=True)

        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[project]\nname = "runpod-flash"\n')

        deps = _extract_runpod_flash_dependencies(pkg_dir)
        assert deps == []


class TestFindRunpodFlashEdgeCases:
    """Edge cases for _find_runpod_flash not covered by existing tests."""

    def test_find_spec_raises_exception(self, tmp_path):
        """Returns None when find_spec raises (doesn't propagate)."""
        from unittest.mock import patch

        with patch(
            "runpod_flash.cli.commands.build.importlib.util.find_spec",
            side_effect=ModuleNotFoundError("broken"),
        ):
            result = _find_runpod_flash(tmp_path)

        # Falls through to directory search, which won't find anything
        assert result is None

    def test_find_spec_returns_spec_without_origin(self, tmp_path):
        """Falls to directory search when spec.origin is None."""
        from unittest.mock import MagicMock, patch

        mock_spec = MagicMock()
        mock_spec.origin = None

        with patch(
            "runpod_flash.cli.commands.build.importlib.util.find_spec",
            return_value=mock_spec,
        ):
            result = _find_runpod_flash(tmp_path)

        # No flash repo in tmp_path, so returns None
        assert result is None
