from pathlib import Path

from runpod_flash.cli.commands.build import augment_with_local_modules


def test_force_includes_module_dropped_by_ignore_rule(tmp_path: Path):
    # endpoint imports a module whose name matches the built-in test_*.py ignore rule
    (tmp_path / "test_helpers.py").write_text("def h():\n    return 1\n")
    endpoint = tmp_path / "endpoint.py"
    endpoint.write_text(
        "import test_helpers\n\ndef handler():\n    return test_helpers.h()\n"
    )

    # simulate the ignore filter having dropped test_helpers.py
    files = [endpoint]
    augmented = augment_with_local_modules(files, tmp_path)

    assert (tmp_path / "test_helpers.py") in augmented
    assert endpoint in augmented


def test_leaves_files_untouched_when_no_local_imports(tmp_path: Path):
    endpoint = tmp_path / "endpoint.py"
    endpoint.write_text("import os\n\ndef handler():\n    return os.getpid()\n")
    files = [endpoint]
    assert augment_with_local_modules(files, tmp_path) == [endpoint]
