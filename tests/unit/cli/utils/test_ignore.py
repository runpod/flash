"""Tests for ignore pattern matching utilities."""

import logging
from pathlib import Path

from runpod_flash.cli.utils.ignore import (
    get_file_tree,
    load_ignore_patterns,
    parse_ignore_file,
    should_ignore,
)


class TestParseIgnoreFile:
    def test_parse_existing_gitignore(self, tmp_path):
        """Parse a standard .gitignore file."""
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("*.pyc\n__pycache__/\n.env\n")

        patterns = parse_ignore_file(gitignore)

        assert patterns == ["*.pyc", "__pycache__/", ".env"]

    def test_skip_comments_and_blank_lines(self, tmp_path):
        """Comments and blank lines are stripped."""
        ignore_file = tmp_path / ".gitignore"
        ignore_file.write_text("# comment\n\npattern\n  # indented comment\n")

        patterns = parse_ignore_file(ignore_file)

        assert patterns == ["pattern"]

    def test_missing_file_returns_empty(self, tmp_path):
        """Non-existent file returns empty list without error."""
        missing = tmp_path / "does_not_exist"

        assert parse_ignore_file(missing) == []

    def test_unreadable_file_returns_empty(self, tmp_path, caplog):
        """Unreadable file returns empty list and logs warning."""
        bad_file = tmp_path / "bad"
        bad_file.mkdir()  # directory, not file -- read_text will fail

        with caplog.at_level(logging.WARNING):
            result = parse_ignore_file(bad_file)

        assert result == []
        assert "Failed to read" in caplog.text


class TestLoadIgnorePatterns:
    def test_loads_gitignore_patterns(self, tmp_path):
        """Patterns from .gitignore are included."""
        (tmp_path / ".gitignore").write_text("custom_dir/\n")

        spec = load_ignore_patterns(tmp_path)

        assert spec.match_file("custom_dir/foo.py")

    def test_no_gitignore_still_has_builtins(self, tmp_path):
        """Built-in patterns work even without .gitignore."""
        spec = load_ignore_patterns(tmp_path)

        assert spec.match_file("__pycache__/module.pyc")
        assert spec.match_file(".venv/lib/python3.12/site.py")

    def test_builtin_excludes_test_files(self, tmp_path):
        """Built-in patterns exclude test files from builds."""
        spec = load_ignore_patterns(tmp_path)

        assert spec.match_file("test_worker.py")
        assert spec.match_file("worker_test.py")
        assert spec.match_file("tests/unit/test_foo.py")

    def test_builtin_excludes_markdown_but_keeps_readme(self, tmp_path):
        """*.md excluded, but !README.md negation keeps README."""
        spec = load_ignore_patterns(tmp_path)

        assert spec.match_file("CHANGELOG.md")
        assert spec.match_file("TESTING.md")
        assert not spec.match_file("README.md")

    def test_builtin_excludes_env_files(self, tmp_path):
        """Environment files are excluded."""
        spec = load_ignore_patterns(tmp_path)

        assert spec.match_file(".env")
        assert spec.match_file(".env.local")

    def test_builtin_excludes_build_artifacts(self, tmp_path):
        """Build artifacts and caches are excluded."""
        spec = load_ignore_patterns(tmp_path)

        assert spec.match_file(".flash/server.py")
        assert spec.match_file("dist/package.tar.gz")
        assert spec.match_file("build/lib/mod.py")
        assert spec.match_file("pkg.egg-info/PKG-INFO")

    def test_builtin_excludes_ide_dirs(self, tmp_path):
        """IDE directories are excluded."""
        spec = load_ignore_patterns(tmp_path)

        assert spec.match_file(".vscode/settings.json")
        assert spec.match_file(".idea/workspace.xml")

    def test_worker_files_not_excluded(self, tmp_path):
        """Normal worker files are included."""
        spec = load_ignore_patterns(tmp_path)

        assert not spec.match_file("gpu_worker.py")
        assert not spec.match_file("api.py")
        assert not spec.match_file("lib/utils.py")

    def test_warns_on_existing_flashignore(self, tmp_path, caplog):
        """Warn users who still have a .flashignore file."""
        (tmp_path / ".flashignore").write_text("custom_pattern/\n")

        with caplog.at_level(logging.WARNING):
            load_ignore_patterns(tmp_path)

        assert ".flashignore" in caplog.text
        assert "no longer supported" in caplog.text


class TestShouldIgnore:
    def test_matches_ignored_file(self, tmp_path):
        """Ignored file returns True."""
        spec = load_ignore_patterns(tmp_path)
        ignored = tmp_path / "__pycache__" / "mod.pyc"

        assert should_ignore(ignored, spec, tmp_path)

    def test_included_file(self, tmp_path):
        """Normal file returns False."""
        spec = load_ignore_patterns(tmp_path)
        included = tmp_path / "worker.py"

        assert not should_ignore(included, spec, tmp_path)

    def test_path_outside_base_dir_returns_false(self, tmp_path):
        """File not relative to base_dir returns False."""
        spec = load_ignore_patterns(tmp_path)
        outside = Path("/completely/different/path.py")

        assert not should_ignore(outside, spec, tmp_path)


class TestGetFileTree:
    def test_collects_included_files(self, tmp_path):
        """Returns files not matching ignore patterns."""
        (tmp_path / "worker.py").write_text("code")
        (tmp_path / "utils.py").write_text("code")

        spec = load_ignore_patterns(tmp_path)
        files = get_file_tree(tmp_path, spec)

        names = {f.name for f in files}
        assert "worker.py" in names
        assert "utils.py" in names

    def test_excludes_ignored_files(self, tmp_path):
        """Ignored files are not returned."""
        (tmp_path / "worker.py").write_text("code")
        cache_dir = tmp_path / "__pycache__"
        cache_dir.mkdir()
        (cache_dir / "mod.cpython-312.pyc").write_text("bytecode")

        spec = load_ignore_patterns(tmp_path)
        files = get_file_tree(tmp_path, spec)

        names = {f.name for f in files}
        assert "worker.py" in names
        assert "mod.cpython-312.pyc" not in names

    def test_excludes_test_files_from_tree(self, tmp_path):
        """test_*.py files are pruned from the file tree."""
        (tmp_path / "worker.py").write_text("code")
        (tmp_path / "test_worker.py").write_text("test code")

        spec = load_ignore_patterns(tmp_path)
        files = get_file_tree(tmp_path, spec)

        names = {f.name for f in files}
        assert "worker.py" in names
        assert "test_worker.py" not in names

    def test_recurses_into_subdirectories(self, tmp_path):
        """Recursively collects files from subdirectories."""
        sub = tmp_path / "lib"
        sub.mkdir()
        (sub / "helper.py").write_text("code")

        spec = load_ignore_patterns(tmp_path)
        files = get_file_tree(tmp_path, spec)

        names = {f.name for f in files}
        assert "helper.py" in names
