#
# nix/checks/default.nix — runpod-flash
#
# Aggregates the checks run by `nix flake check`. Each check is a
# self-contained derivation that runs one tool against the project's own
# configuration in a sandbox — no network.
#
# Each check's `src` is scoped with `lib.fileset` to only the files that can
# affect its result, so derivations stay small and cache well: editing a
# Markdown doc invalidates nothing; editing a `.nix` file rebuilds only the
# nixfmt check; editing a `.sh` script rebuilds only shellcheck. This is what
# keeps `nix flake check` fast on the common edit-one-thing loop.
#
# The gate mirrors what the uv-based CI actually blocks on: ruff lint + format
# and the unit test suite, plus the Nix-native nixfmt + shellcheck. No uv, no
# network.
#
# Deliberately NOT hard gates (kept in the dev shell, run via `check-types` /
# `check-security`), matching the project's existing policy:
#   - mypy   — the tree has pre-existing type errors; CI only runs it under the
#              aspirational `quality-check-strict`, never as a merge gate.
#   - bandit — the Makefile runs it non-fatally ("informational").
#   - the integration suite — needs live Runpod, which the sandbox denies.
#
{
  pkgs,
  lib,
  src,
  pythonEnv,
}:
let
  fs = lib.fileset;

  # Every check is a shellchecked writeShellApplication + a one-line runner.
  mkCheck = import ./mk-check.nix { inherit pkgs lib; };

  # ---- Scoped source sets -------------------------------------------------
  # Each is the minimal fileset a given tool reads. `fileFilter` walks the
  # (git-tracked) tree once and keeps only matching files, so the resulting
  # store path — and thus the derivation's input hash — changes only when a
  # relevant file changes.

  pyprojectToml = fs.fileFilter (f: f.name == "pyproject.toml") src;

  # ruff lints/formats every `.py` in the repo (src, tests, e2e, scripts),
  # reading its config from pyproject.toml. Matches `ruff {check,format} .`.
  ruffSrc = fs.toSource {
    root = src;
    fileset = fs.unions [
      (fs.fileFilter (f: f.hasExt "py") src)
      pyprojectToml
    ];
  };

  # pytest needs the importable package (all of src/, including non-.py package
  # data), the tests, and the pytest/coverage config in pyproject.toml.
  pytestSrc = fs.toSource {
    root = src;
    fileset = fs.unions [
      (src + "/src")
      (src + "/tests")
      pyprojectToml
    ];
  };

  # nixfmt / shellcheck each see only their own file type.
  nixSrc = fs.toSource {
    root = src;
    fileset = fs.fileFilter (f: f.hasExt "nix") src;
  };
  shSrc = fs.toSource {
    root = src;
    fileset = fs.fileFilter (f: f.hasExt "sh") src;
  };

  # Walk the tree for a whole-file-type tool (nixfmt, shellcheck): every matching
  # file, NUL-delimited so paths with spaces are safe, `-r` so an empty match is
  # not an error.
  walk = ext: tool: "find . -name '*.${ext}' -print0 | xargs -0 -r ${tool}";

  # The simple checks are pure data — a tool, its scoped source, and the command
  # to run. pytest is the one bespoke check (two passes, env exports), so it is
  # defined separately in ./pytest.nix rather than in this table.
  simpleChecks = {
    ruff-lint = {
      runtimeInputs = [ pkgs.ruff ];
      src = ruffSrc;
      text = "ruff check .";
    };
    ruff-format = {
      runtimeInputs = [ pkgs.ruff ];
      src = ruffSrc;
      text = "ruff format --check .";
    };
    nixfmt = {
      runtimeInputs = [ pkgs.nixfmt ];
      src = nixSrc;
      text = walk "nix" "nixfmt --check";
    };
    shellcheck = {
      runtimeInputs = [ pkgs.shellcheck ];
      src = shSrc;
      text = walk "sh" "shellcheck";
    };
  };
in
lib.mapAttrs (
  name: c:
  mkCheck {
    name = "flash-${name}";
    inherit (c) src runtimeInputs text;
  }
) simpleChecks
// {
  pytest = import ./pytest.nix {
    inherit mkCheck pkgs pythonEnv;
    src = pytestSrc;
  };
}
