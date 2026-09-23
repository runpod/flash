#
# nix/python/env.nix — runpod-flash
#
# The project's Python environment, built entirely from Nix — no uv, no
# virtualenv, no PyPI fetch at dev/test time. This single interpreter env
# carries flash's runtime dependencies (from ./deps.nix) plus the test/typecheck
# toolchain, so it backs both the dev shell and the hermetic `pytest` check.
#
# `runpod` and its transitive `tqdm-loggable` come from ../packages/ (not yet in
# nixpkgs); everything else is stock nixpkgs for the pinned interpreter.
#
{
  python,
  runpod,
}:
let
  runtimeDeps = import ./deps.nix { inherit runpod; };
in
python.withPackages (
  ps:
  runtimeDeps ps
  ++ [
    # Test toolchain (mirror [dependency-groups].test, minus twine — PyPI is
    # no longer a distribution target).
    ps.pytest
    ps.pytest-mock
    ps.pytest-asyncio
    ps.pytest-cov
    ps.pytest-xdist
    ps.pytest-timeout
  ]
  ++ [
    # Typecheck + dev tooling that needs the full importable graph.
    ps.mypy
    ps.mcp
  ]
)
