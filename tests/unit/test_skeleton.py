"""
Unit tests for project skeleton creation utilities.

Tests the skeleton module functionality:
- Ignore pattern matching
- File conflict detection
- Project skeleton creation
- Hidden file handling
- Template substitution
- Force overwrite behavior
"""

from pathlib import Path

import pytest

from runpod_flash.cli.utils.skeleton import (
    IGNORE_PATTERNS,
    _should_ignore,
    create_project_skeleton,
    detect_file_conflicts,
)


class TestIgnorePatterns:
    """Test ignore pattern matching functionality."""

    def test_should_ignore_pycache_directory(self):
        """Test that __pycache__ directories are ignored."""
        assert _should_ignore(Path("__pycache__"))
        assert _should_ignore(Path("src/__pycache__"))
        assert _should_ignore(Path("src/foo/__pycache__"))

    def test_should_ignore_pyc_files(self):
        """Test that .pyc files are ignored."""
        assert _should_ignore(Path("test.pyc"))
        assert _should_ignore(Path("module.pyo"))
        assert _should_ignore(Path("script.pyd"))

    def test_should_ignore_os_files(self):
        """Test that OS-specific files are ignored."""
        assert _should_ignore(Path(".DS_Store"))
        assert _should_ignore(Path("Thumbs.db"))

    def test_should_ignore_git_directory(self):
        """Test that .git directory is ignored."""
        assert _should_ignore(Path(".git"))
        assert _should_ignore(Path("src/.git"))

    def test_should_ignore_pytest_cache(self):
        """Test that pytest cache is ignored."""
        assert _should_ignore(Path(".pytest_cache"))

    def test_should_ignore_egg_info(self):
        """Test that egg-info directories are ignored."""
        assert _should_ignore(Path("package.egg-info"))

    def test_should_not_ignore_valid_files(self):
        """Test that valid Python files are not ignored."""
        assert not _should_ignore(Path("main.py"))
        assert not _should_ignore(Path("test_module.py"))
        assert not _should_ignore(Path("__init__.py"))

    def test_should_not_ignore_hidden_template_files(self):
        """Test that template hidden files are not ignored."""
        assert not _should_ignore(Path(".env.example"))
        assert not _should_ignore(Path(".gitignore"))

    def test_ignore_patterns_constant_exists(self):
        """Test that IGNORE_PATTERNS constant is defined."""
        assert isinstance(IGNORE_PATTERNS, set)
        assert len(IGNORE_PATTERNS) > 0
        assert "__pycache__" in IGNORE_PATTERNS


class TestDetectFileConflicts:
    """Test file conflict detection functionality."""

    def test_detect_no_conflicts_empty_directory(self, tmp_path):
        """Test that no conflicts are detected in empty directory."""
        conflicts = detect_file_conflicts(tmp_path)
        assert conflicts == []

    def test_detect_conflict_with_existing_file(self, tmp_path):
        """Test that existing files are detected as conflicts."""
        # Create a file that exists in the template
        (tmp_path / "gpu_worker.py").write_text("# existing file")

        conflicts = detect_file_conflicts(tmp_path)

        # Should detect gpu_worker.py as a conflict
        conflict_names = [str(c) for c in conflicts]
        assert "gpu_worker.py" in conflict_names

    def test_detect_conflict_with_hidden_file(self, tmp_path):
        """Test that existing hidden files are detected as conflicts."""
        (tmp_path / ".env.example").write_text("EXISTING=true")

        conflicts = detect_file_conflicts(tmp_path)

        conflict_names = [str(c) for c in conflicts]
        assert ".env.example" in conflict_names

    def test_ignore_pycache_in_conflict_detection(self, tmp_path):
        """Test that __pycache__ is ignored during conflict detection."""
        # Create __pycache__ directory
        pycache_dir = tmp_path / "__pycache__"
        pycache_dir.mkdir()
        (pycache_dir / "test.pyc").write_text("compiled")

        conflicts = detect_file_conflicts(tmp_path)

        # __pycache__ should not be in conflicts
        conflict_names = [str(c) for c in conflicts]
        assert "__pycache__" not in conflict_names
        assert "test.pyc" not in conflict_names

    def test_detect_conflicts_nonexistent_template_dir(self, tmp_path, monkeypatch):
        """Test handling when template directory doesn't exist."""
        # Patch __file__ to point to a location where skeleton_template doesn't exist
        mock_file = str(tmp_path / "mock_skeleton.py")
        monkeypatch.setattr("runpod_flash.cli.utils.skeleton.__file__", mock_file)

        # Should return empty list, not raise exception
        conflicts = detect_file_conflicts(tmp_path)
        assert conflicts == []


class TestCreateProjectSkeleton:
    """Test project skeleton creation functionality."""

    def test_create_skeleton_in_empty_directory(self, tmp_path):
        """Test creating skeleton in empty directory."""
        created_files = create_project_skeleton(tmp_path)

        # Should create files
        assert len(created_files) > 0

        # Check that key files exist
        assert (tmp_path / "gpu_worker.py").exists()
        assert (tmp_path / "cpu_worker.py").exists()
        assert (tmp_path / "lb_worker.py").exists()
        assert (tmp_path / "README.md").exists()
        assert (tmp_path / "requirements.txt").exists()

        # Check that hidden files exist
        assert (tmp_path / ".env.example").exists()
        assert (tmp_path / ".gitignore").exists()

    def test_create_skeleton_with_project_name_substitution(self, tmp_path):
        """Test that {{project_name}} placeholder is replaced."""
        project_dir = tmp_path / "my_test_project"
        create_project_skeleton(project_dir)

        # Read a file that might contain the project name
        readme_content = (project_dir / "README.md").read_text()

        # Should contain actual project name, not placeholder
        assert "{{project_name}}" not in readme_content
        assert "my_test_project" in readme_content

    def test_create_skeleton_skips_existing_files_without_force(self, tmp_path):
        """Test that existing files are not overwritten without force flag."""
        # Create an existing file with specific content
        existing_content = "# This is my custom gpu_worker.py"
        (tmp_path / "gpu_worker.py").write_text(existing_content)

        # Create skeleton without force
        create_project_skeleton(tmp_path, force=False)

        # Existing file should not be overwritten
        assert (tmp_path / "gpu_worker.py").read_text() == existing_content

        # But other files should be created
        assert (tmp_path / ".env.example").exists()

    def test_create_skeleton_overwrites_with_force(self, tmp_path):
        """Test that existing files are overwritten with force=True."""
        # Create an existing file
        existing_content = "# This is my custom gpu_worker.py"
        (tmp_path / "gpu_worker.py").write_text(existing_content)

        # Create skeleton with force
        create_project_skeleton(tmp_path, force=True)

        # Existing file should be overwritten
        new_content = (tmp_path / "gpu_worker.py").read_text()
        assert new_content != existing_content
        assert "# This is my custom gpu_worker.py" not in new_content

    def test_create_skeleton_ignores_pycache(self, tmp_path):
        """Test that __pycache__ directories are not copied."""
        created_files = create_project_skeleton(tmp_path)

        # Check that no __pycache__ was created
        created_file_names = [str(f) for f in created_files]
        assert not any("__pycache__" in f for f in created_file_names)

        # Verify no __pycache__ in actual filesystem
        all_dirs = list(tmp_path.rglob("*"))
        pycache_dirs = [d for d in all_dirs if d.name == "__pycache__"]
        assert len(pycache_dirs) == 0

    def test_create_skeleton_ignores_pyc_files(self, tmp_path):
        """Test that .pyc files are not copied."""
        created_files = create_project_skeleton(tmp_path)

        # Check that no .pyc files were created
        created_file_names = [str(f) for f in created_files]
        assert not any(f.endswith(".pyc") for f in created_file_names)

    def test_create_skeleton_creates_parent_directories(self, tmp_path):
        """Test that parent directories are created automatically."""
        project_dir = tmp_path / "nested" / "path" / "project"

        # Should not raise exception
        create_project_skeleton(project_dir)

        # All parent directories should exist
        assert project_dir.exists()
        assert (project_dir / "gpu_worker.py").exists()

    def test_create_skeleton_returns_created_files_list(self, tmp_path):
        """Test that function returns list of created files."""
        created_files = create_project_skeleton(tmp_path)

        # Should return a list of strings
        assert isinstance(created_files, list)
        assert all(isinstance(f, str) for f in created_files)

        # Should contain expected files
        assert "gpu_worker.py" in created_files
        assert ".env.example" in created_files
        assert "README.md" in created_files

    def test_create_skeleton_handles_readonly_files_gracefully(self, tmp_path):
        """Test handling of read-only files during creation."""
        # Create a read-only file
        readonly_file = tmp_path / "gpu_worker.py"
        readonly_file.write_text("# readonly")
        readonly_file.chmod(0o444)

        try:
            # Should not raise exception with force=False
            created_files = create_project_skeleton(tmp_path, force=False)

            # Should still create other files
            assert ".env.example" in created_files
        finally:
            # Cleanup: restore write permissions
            readonly_file.chmod(0o644)

    def test_create_skeleton_raises_error_if_template_missing(
        self, tmp_path, monkeypatch
    ):
        """Test that appropriate error is raised if template directory is missing."""

        # Mock the template directory to not exist
        def mock_exists(self):
            return False

        monkeypatch.setattr(Path, "exists", mock_exists)

        with pytest.raises(FileNotFoundError, match="Template directory not found"):
            create_project_skeleton(tmp_path)


class TestEndToEndScenarios:
    """Test end-to-end scenarios for skeleton creation."""

    def test_full_init_workflow_in_place(self, tmp_path):
        """Test complete workflow for in-place initialization."""
        # Check for conflicts (should be none)
        conflicts = detect_file_conflicts(tmp_path)
        assert len(conflicts) == 0

        # Create skeleton
        created_files = create_project_skeleton(tmp_path)
        assert len(created_files) > 0

        # Verify all expected files exist
        expected_files = [
            "gpu_worker.py",
            "cpu_worker.py",
            "lb_worker.py",
            "README.md",
            "requirements.txt",
            ".env.example",
            ".gitignore",
        ]
        for filename in expected_files:
            assert (tmp_path / filename).exists(), f"{filename} should exist"

    def test_full_init_workflow_with_conflicts(self, tmp_path):
        """Test complete workflow when conflicts exist."""
        # Create some existing files
        (tmp_path / "gpu_worker.py").write_text("# my custom worker")
        (tmp_path / ".env.example").write_text("MY_VAR=123")

        # Detect conflicts
        conflicts = detect_file_conflicts(tmp_path)
        assert len(conflicts) == 2

        conflict_names = [str(c) for c in conflicts]
        assert "gpu_worker.py" in conflict_names
        assert ".env.example" in conflict_names

        # Create skeleton without force (should preserve existing)
        create_project_skeleton(tmp_path, force=False)

        # Check that existing files were preserved
        assert (tmp_path / "gpu_worker.py").read_text() == "# my custom worker"
        assert (tmp_path / ".env.example").read_text() == "MY_VAR=123"

        # But new files should be created
        assert (tmp_path / "README.md").exists()

    def test_hidden_files_are_copied(self, tmp_path):
        """Test that all hidden template files are copied correctly."""
        create_project_skeleton(tmp_path)

        hidden_files = [".env.example", ".gitignore"]

        for hidden_file in hidden_files:
            file_path = tmp_path / hidden_file
            assert file_path.exists(), f"{hidden_file} should exist"
            assert file_path.is_file(), f"{hidden_file} should be a file"
            # Hidden files should have content
            content = file_path.read_text()
            assert len(content) > 0, f"{hidden_file} should not be empty"

    def test_no_ignored_files_in_output(self, tmp_path):
        """Test that ignored patterns are never in created output."""
        created_files = create_project_skeleton(tmp_path)

        # Check created files list
        for created_file in created_files:
            path = Path(created_file)
            assert not _should_ignore(path), (
                f"Created file {created_file} should not be ignored"
            )

        # Check actual filesystem
        all_files = list(tmp_path.rglob("*"))
        for file_path in all_files:
            relative_path = file_path.relative_to(tmp_path)
            # Skip checking against root directory itself
            if relative_path != Path("."):
                assert not _should_ignore(relative_path), (
                    f"File {relative_path} should not be ignored"
                )
