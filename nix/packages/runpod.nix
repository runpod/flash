#
# nix/packages/runpod.nix — runpod-flash
#
# The `runpod` SDK is not in nixpkgs, so we build it from PyPI here. flash's
# [project.dependencies] just names "runpod" (the git-main pin lives only in
# [tool.uv.sources], which is a dev-only concern), so a normal PyPI build is
# the right dependency for the packaged flash CLI.
#
# runpod pins some bounds tightly (e.g. colorama, aiohttp); we relax those
# against the versions nixpkgs ships rather than vendoring exact pins.
#
{
  pkgs,
  lib,
  python,
}:
let
  py = python.pkgs;
  tqdm-loggable = import ./tqdm-loggable.nix { inherit pkgs lib python; };
in
py.buildPythonPackage rec {
  pname = "runpod";
  version = "1.12.0";
  pyproject = true;

  src = pkgs.fetchPypi {
    inherit pname version;
    hash = "sha256-URxrdRIhqYkEUKot3twMUNTWSqOgCKqw16I6hHktu4U=";
  };

  build-system = [
    py.setuptools
    py.setuptools-scm
  ];

  # Building from the PyPI sdist, so there is no git tag for setuptools_scm to
  # read; hand it the known version explicitly.
  env.SETUPTOOLS_SCM_PRETEND_VERSION = version;

  # Relax runpod's tight lower/upper bounds to the versions nixpkgs provides.
  pythonRelaxDeps = true;

  dependencies = [
    py.aiohttp
    py.aiohttp-retry
    py.backoff
    py.boto3
    py.click
    py.colorama
    py.cryptography
    py.fastapi
    py.paramiko
    py.prettytable
    py.psutil
    py.py-cpuinfo
    py.inquirerpy
    py.requests
    py.tomli
    py.tomlkit
    py.urllib3
    py.watchdog
    # fastapi[all] extras that runpod exercises at import/serve time:
    py.uvicorn
    py.python-multipart
    py.email-validator
    py.httpx
    py.jinja2
    tqdm-loggable
  ];

  # Network-bound test suite; skip in the sandbox.
  doCheck = false;

  pythonImportsCheck = [ "runpod" ];

  meta = {
    description = "Runpod Python SDK";
    homepage = "https://github.com/runpod/runpod-python";
    license = lib.licenses.mit;
  };
}
