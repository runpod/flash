"""Tests for build.py helper functions: _bundle_runpod_flash,
_remove_runpod_flash_from_requirements.

These functions are always mocked in existing build tests; these tests
exercise them directly.
"""

import os
import stat
from pathlib import Path

import pytest

from runpod_flash.cli.commands.build import (
    _bundle_runpod_flash,
    _find_runpod_flash,
    _make_owner_writable,
    _remove_runpod_flash_from_requirements,
    create_build_directory,
)


def _make_read_only(root: Path) -> None:
    """Strip write bits like the Nix store does (files 0444, dirs 0555)."""
    for path in sorted(root.rglob("*"), reverse=True):
        path.chmod(0o555 if path.is_dir() else 0o444)
    root.chmod(0o555)


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

    def test_read_only_source_produces_writable_copy(self, tmp_path):
        """A read-only install (the Nix store) bundles into writable files."""
        flash_pkg = tmp_path / "source" / "runpod_flash"
        runtime = flash_pkg / "runtime"
        runtime.mkdir(parents=True)
        (flash_pkg / "__init__.py").write_text("")
        (runtime / "_flash_resource_config.py").write_text("# placeholder")
        _make_read_only(flash_pkg)

        build_dir = tmp_path / "build"
        build_dir.mkdir()

        try:
            _bundle_runpod_flash(build_dir, flash_pkg)

            config = (
                build_dir / "runpod_flash" / "runtime" / "_flash_resource_config.py"
            )
            config.write_text("# generated")
            assert config.read_text() == "# generated"
            assert os.stat(config.parent).st_mode & stat.S_IWUSR
        finally:
            for path in (flash_pkg, *flash_pkg.rglob("*")):
                path.chmod(0o755)


class TestCreateBuildDirectory:
    """Direct tests for create_build_directory."""

    def test_removes_read_only_build_tree(self, tmp_path):
        """A read-only tree left by an older build is removed."""
        stale = tmp_path / ".flash" / ".build" / "runpod_flash" / "runtime"
        stale.mkdir(parents=True)
        (stale / "_flash_resource_config.py").write_text("# stale")
        _make_read_only(tmp_path / ".flash" / ".build")

        build_dir = create_build_directory(tmp_path, "app")

        assert build_dir.is_dir()
        assert not (build_dir / "runpod_flash").exists()


def _tree_read_only_nested(root: Path) -> Path:
    target = root / "a" / "b" / "file.py"
    target.parent.mkdir(parents=True)
    target.write_text("")
    _make_read_only(root)
    return target


def _tree_already_writable(root: Path) -> Path:
    target = root / "file.py"
    target.write_text("")
    return target


def _tree_empty(root: Path) -> Path:
    root.chmod(0o555)
    return root


class TestMakeOwnerWritable:
    """Direct tests for _make_owner_writable."""

    @pytest.mark.parametrize(
        "build_tree",
        [
            pytest.param(_tree_read_only_nested, id="read-only nested tree"),
            pytest.param(_tree_already_writable, id="already writable is a no-op"),
            pytest.param(_tree_empty, id="read-only empty root"),
        ],
    )
    def test_makes_tree_owner_writable(self, tmp_path, build_tree):
        root = tmp_path / "root"
        root.mkdir()
        target = build_tree(root)

        _make_owner_writable(root)

        for path in (root, *root.rglob("*")):
            assert os.stat(path).st_mode & stat.S_IWUSR, path
        assert target.exists()

    def test_skips_broken_symlink(self, tmp_path):
        """A dangling symlink is skipped instead of stat()'d."""
        (tmp_path / "dangling").symlink_to(tmp_path / "missing")

        _make_owner_writable(tmp_path)

        assert (tmp_path / "dangling").is_symlink()


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
