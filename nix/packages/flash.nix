#
# nix/packages/flash.nix — runpod-flash
#
# The packaged flash CLI (`packages.default` / `apps.default`). A standard
# setuptools build of this repo, with runtime deps taken from the shared list in
# ../python/deps.nix (nixpkgs deps plus the custom `runpod` derivation).
#
# This is what backs `nix build .#default`, `nix run .#default -- --help`, and
# `nix profile install github:runpod/flash`.
#
{
  pkgs,
  lib,
  python,
  runpod,
  src,
}:
let
  py = python.pkgs;
  runtimeDeps = import ../python/deps.nix { inherit runpod; };
  # Single source of truth for the version: [project].version in pyproject.toml,
  # which release-please bumps. No hardcoded duplicate to drift.
  pyprojectToml = builtins.fromTOML (builtins.readFile ../../pyproject.toml);
in
py.buildPythonApplication {
  pname = "runpod-flash";
  version = pyprojectToml.project.version;
  pyproject = true;

  inherit src;

  build-system = [
    py.setuptools
    py.wheel
  ];

  # The nine runtime deps come from the shared list; `tomli` is only a build-time
  # backport for pre-3.11 interpreters (a no-op on the pinned 3.14).
  dependencies = runtimeDeps py ++ lib.optionals (py.pythonOlder "3.11") [ py.tomli ];

  # Tests need the dev/test dependency groups and network mocks; the dev shell
  # runs the suite (see ../dev/shell.nix). Keep the package build to an import
  # smoke-test.
  doCheck = false;

  pythonImportsCheck = [ "runpod_flash" ];

  meta = {
    description = "Python SDK for distributed inference and serving on Runpod serverless";
    homepage = "https://github.com/runpod/flash";
    license = lib.licenses.mit;
    mainProgram = "flash";
  };
}
