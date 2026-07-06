import sys

from runpod_flash.runtime.module_loader import materialized_modules


def test_empty_modules_is_noop():
    before = list(sys.path)
    with materialized_modules({}) as tmpdir:
        assert tmpdir is None
        assert sys.path == before
    assert sys.path == before


def test_writes_files_and_makes_them_importable():
    before = list(sys.path)
    modules = {"pkg/__init__.py": "\n", "pkg/thing.py": "def val():\n    return 42\n"}
    with materialized_modules(modules) as tmpdir:
        assert tmpdir in sys.path
        namespace: dict = {}
        exec("from pkg.thing import val\nresult = val()", namespace)
        assert namespace["result"] == 42
    # sys.path restored and temp dir gone after exit
    assert sys.path == before


def test_restores_sys_path_on_exception():
    before = list(sys.path)
    try:
        with materialized_modules({"m.py": "x = 1\n"}):
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert sys.path == before
