"""Tests for cli/utils/ignore.py - ignore pattern matching utilities."""

from pathlib import Path
from unittest.mock import patch


from runpod_flash.cli.utils.ignore import (
    get_file_tree,
    load_ignore_patterns,
    parse_ignore_file,
    should_ignore,
)


class TestParseIgnoreFile:
    """Test parse_ignore_file function."""

    def test_parses_patterns(self, tmp_path):
        """Parses patterns from an ignore file."""
        ignore_file = tmp_path / ".gitignore"
        ignore_file.write_text("*.pyc\n__pycache__/\n.env\n")

        patterns = parse_ignore_file(ignore_file)
        assert "*.pyc" in patterns
        assert "__pycache__/" in patterns
        assert ".env" in patterns

    def test_skips_comments(self, tmp_path):
        """Skips comment lines starting with #."""
        ignore_file = tmp_path / ".gitignore"
        ignore_file.write_text("# This is a comment\n*.pyc\n# Another comment\n.env\n")

        patterns = parse_ignore_file(ignore_file)
        assert len(patterns) == 2
        assert "*.pyc" in patterns
        assert ".env" in patterns

    def test_skips_empty_lines(self, tmp_path):
        """Skips empty lines."""
        ignore_file = tmp_path / ".gitignore"
        ignore_file.write_text("\n*.pyc\n\n\n.env\n\n")

        patterns = parse_ignore_file(ignore_file)
        assert len(patterns) == 2

    def test_missing_file_returns_empty(self, tmp_path):
        """Returns empty list for non-existent file."""
        patterns = parse_ignore_file(tmp_path / "nonexistent")
        assert patterns == []

    def test_read_error_returns_empty(self, tmp_path):
        """Returns empty list on read errors."""
        ignore_file = tmp_path / ".gitignore"
        ignore_file.write_text("*.pyc")

        with patch.object(Path, "read_text", side_effect=PermissionError("denied")):
            patterns = parse_ignore_file(ignore_file)
        assert patterns == []

    def test_strips_whitespace(self, tmp_path):
        """Strips leading/trailing whitespace from patterns."""
        ignore_file = tmp_path / ".gitignore"
        ignore_file.write_text("  *.pyc  \n  .env  \n")

        patterns = parse_ignore_file(ignore_file)
        assert "*.pyc" in patterns
        assert ".env" in patterns


class TestLoadIgnorePatterns:
    """Test load_ignore_patterns function."""

    def test_loads_flashignore(self, tmp_path):
        """Loads patterns from .flashignore."""
        (tmp_path / ".flashignore").write_text("custom_pattern\n")

        spec = load_ignore_patterns(tmp_path)
        assert spec.match_file("custom_pattern")

    def test_loads_gitignore(self, tmp_path):
        """Loads patterns from .gitignore."""
        (tmp_path / ".gitignore").write_text("*.log\n")

        spec = load_ignore_patterns(tmp_path)
        assert spec.match_file("test.log")

    def test_combines_both_files(self, tmp_path):
        """Combines patterns from both .flashignore and .gitignore."""
        (tmp_path / ".flashignore").write_text("flash_specific\n")
        (tmp_path / ".gitignore").write_text("git_specific\n")

        spec = load_ignore_patterns(tmp_path)
        assert spec.match_file("flash_specific")
        assert spec.match_file("git_specific")

    def test_always_ignore_patterns(self, tmp_path):
        """Always includes built-in ignore patterns."""
        spec = load_ignore_patterns(tmp_path)
        assert spec.match_file("__pycache__/cache.pyc")
        assert spec.match_file(".git/config")
        assert spec.match_file(".venv/lib/python3.11")
        assert spec.match_file("build.tar.gz")

    def test_no_ignore_files(self, tmp_path):
        """Works when no ignore files exist."""
        spec = load_ignore_patterns(tmp_path)
        # Still has always_ignore patterns
        assert spec.match_file("test.pyc")


class TestShouldIgnore:
    """Test should_ignore function."""

    def test_matches_ignore_pattern(self, tmp_path):
        """Returns True for files matching patterns."""
        spec = load_ignore_patterns(tmp_path)
        file_path = tmp_path / "test.pyc"
        assert should_ignore(file_path, spec, tmp_path) is True

    def test_non_matching_file(self, tmp_path):
        """Returns False for files not matching any pattern."""
        spec = load_ignore_patterns(tmp_path)
        file_path = tmp_path / "main.py"
        assert should_ignore(file_path, spec, tmp_path) is False

    def test_path_not_relative_to_base(self, tmp_path):
        """Returns False when file_path is not relative to base_dir."""
        spec = load_ignore_patterns(tmp_path)
        other_dir = Path("/completely/different/path")
        assert should_ignore(other_dir / "test.py", spec, tmp_path) is False


class TestGetFileTree:
    """Test get_file_tree function."""

    def test_collects_files(self, tmp_path):
        """Collects non-ignored files."""
        (tmp_path / "main.py").write_text("code")
        (tmp_path / "utils.py").write_text("code")

        spec = load_ignore_patterns(tmp_path)
        files = get_file_tree(tmp_path, spec)
        filenames = [f.name for f in files]
        assert "main.py" in filenames
        assert "utils.py" in filenames

    def test_skips_ignored_files(self, tmp_path):
        """Skips files matching ignore patterns."""
        (tmp_path / "main.py").write_text("code")
        (tmp_path / "test.pyc").write_text("compiled")

        spec = load_ignore_patterns(tmp_path)
        files = get_file_tree(tmp_path, spec)
        filenames = [f.name for f in files]
        assert "main.py" in filenames
        assert "test.pyc" not in filenames

    def test_recurses_subdirectories(self, tmp_path):
        """Recursively collects files from subdirectories."""
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (subdir / "nested.py").write_text("code")
        (tmp_path / "top.py").write_text("code")

        spec = load_ignore_patterns(tmp_path)
        files = get_file_tree(tmp_path, spec)
        filenames = [f.name for f in files]
        assert "top.py" in filenames
        assert "nested.py" in filenames

    def test_default_base_dir(self, tmp_path):
        """Uses directory as base_dir when not specified."""
        (tmp_path / "file.py").write_text("code")

        spec = load_ignore_patterns(tmp_path)
        files = get_file_tree(tmp_path, spec)
        assert len(files) >= 1

    def test_permission_error_handled(self, tmp_path):
        """Handles permission errors gracefully."""
        (tmp_path / "file.py").write_text("code")

        spec = load_ignore_patterns(tmp_path)

        with patch.object(Path, "iterdir", side_effect=PermissionError("denied")):
            files = get_file_tree(tmp_path, spec)
        assert files == []

    def test_skips_ignored_directories(self, tmp_path):
        """Skips entire ignored directories."""
        pycache = tmp_path / "__pycache__"
        pycache.mkdir()
        (pycache / "module.cpython-311.pyc").write_text("compiled")
        (tmp_path / "main.py").write_text("code")

        spec = load_ignore_patterns(tmp_path)
        files = get_file_tree(tmp_path, spec)
        filenames = [f.name for f in files]
        assert "main.py" in filenames
        assert "module.cpython-311.pyc" not in filenames
