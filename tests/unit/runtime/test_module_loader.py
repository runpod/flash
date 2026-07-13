import sys
import tempfile
from pathlib import Path

import pytest

from runpod_flash.runtime import module_loader
from runpod_flash.runtime.module_loader import materialized_modules


@pytest.fixture
def captured_tmpdirs(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record every temp dir ``materialized_modules`` creates, to assert cleanup."""
    created: list[str] = []
    real_mkdtemp = tempfile.mkdtemp

    def _spy(*args: object, **kwargs: object) -> str:
        path = real_mkdtemp(*args, **kwargs)
        created.append(path)
        return path

    monkeypatch.setattr(module_loader.tempfile, "mkdtemp", _spy)
    return created


def test_empty_modules_is_noop():
    before = list(sys.path)
    with materialized_modules({}) as tmpdir:
        assert tmpdir is None
        assert sys.path == before
    assert sys.path == before


def test_writes_files_and_makes_them_importable(captured_tmpdirs: list[str]):
    before = list(sys.path)
    modules = {"pkg/__init__.py": "\n", "pkg/thing.py": "def val():\n    return 42\n"}
    with materialized_modules(modules) as tmpdir:
        assert tmpdir in sys.path
        namespace: dict = {}
        exec("from pkg.thing import val\nresult = val()", namespace)
        assert namespace["result"] == 42
    # sys.path restored and temp dir removed from disk after exit
    assert sys.path == before
    assert not Path(captured_tmpdirs[0]).exists()


def test_restores_sys_path_on_exception():
    before = list(sys.path)
    try:
        with materialized_modules({"m.py": "x = 1\n"}):
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert sys.path == before


@pytest.mark.parametrize(
    "rel_path", ["/etc/evil.py", "../evil.py", "pkg/../../evil.py"]
)
def test_rejects_paths_that_escape_temp_dir(rel_path: str, captured_tmpdirs: list[str]):
    # ``modules`` is untrusted; a path that resolves outside the temp dir must be
    # rejected before any write, sys.path left untouched, and the temp dir removed.
    before = list(sys.path)
    with pytest.raises(ValueError, match="escapes materialization dir"):
        with materialized_modules({rel_path: "x = 1\n"}):
            pass
    assert sys.path == before
    assert not Path(captured_tmpdirs[0]).exists()


def test_rejects_escape_after_valid_entry_and_cleans_up(captured_tmpdirs: list[str]):
    # The guard fires mid-loop: a valid module is written first, then an escaping
    # key must still raise and the partially-populated temp dir must be removed
    # (regression guard for the temp-dir leak the cleanup restructure fixed).
    before = list(sys.path)
    modules = {"pkg/ok.py": "x = 1\n", "../evil.py": "y = 2\n"}
    with pytest.raises(ValueError, match="escapes materialization dir"):
        with materialized_modules(modules):
            pass
    assert sys.path == before
    assert not Path(captured_tmpdirs[0]).exists()
