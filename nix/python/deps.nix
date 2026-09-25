#
# nix/python/deps.nix — runpod-flash
#
# The single source of truth for flash's runtime dependencies — the Nix mirror
# of pyproject.toml [project.dependencies]. Written once here and consumed by
# BOTH the dev/test interpreter env (./env.nix) and the packaged CLI
# (../packages/flash.nix), so the two lists can never drift.
#
# It is a function of a Python package set `ps` (either the argument
# `python.withPackages` passes, or `python.pkgs`) so each consumer applies it
# against the right interpreter. `runpod` is not in nixpkgs (it is built in
# ../packages/runpod.nix), so it is injected rather than looked up in `ps`.
#
{ runpod }:
ps: [
  ps.cloudpickle
  runpod
  ps.python-dotenv
  ps.pydantic
  ps.rich
  ps.typer
  ps.questionary
  ps.pathspec
  ps.tomlkit
]
