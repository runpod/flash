"""Materialize inline local-module source onto the worker's import path.

The live-serverless path ships local module files in ``FunctionRequest.modules``.
Before the worker ``exec``s the function code, those files must exist on disk and
be importable. This context manager writes them to a temp dir, prepends it to
``sys.path``, and cleans up afterward.
"""

from __future__ import annotations

import logging
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

log = logging.getLogger(__name__)


@contextmanager
def materialized_modules(modules: dict[str, str]) -> Iterator[str | None]:
    """Write *modules* to a temp dir on ``sys.path`` for the duration of the block.

    Args:
        modules: POSIX relative path -> module source text. Empty means no-op.

    Yields:
        The temp dir path added to ``sys.path``, or ``None`` when *modules* is empty.

    Concurrency note: this mutates the process-global ``sys.path``. It assumes one
    function executes at a time per worker process (the current worker model). If a
    worker runs multiple handler invocations concurrently (e.g. async concurrency >
    1), the inserted temp dir is visible to other in-flight invocations and cleanup
    on exit could remove files mid-import. Isolating sys.path per invocation is a
    follow-up if concurrent execution is enabled.
    """
    if not modules:
        yield None
        return

    tmpdir = tempfile.mkdtemp(prefix="flash_modules_")
    root = Path(tmpdir)
    for rel_path, source in modules.items():
        dest = root / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(source, encoding="utf-8")

    sys.path.insert(0, tmpdir)
    try:
        yield tmpdir
    finally:
        try:
            sys.path.remove(tmpdir)
        except ValueError:
            log.warning(
                "flash module temp dir %s already removed from sys.path", tmpdir
            )
        import shutil

        shutil.rmtree(tmpdir, ignore_errors=True)
