#
# nix/packages/tqdm-loggable.nix — runpod-flash
#
# `tqdm-loggable` is a runpod runtime dependency that is not (yet) in nixpkgs.
# It is a tiny pure-Python wrapper over tqdm, so we build it from PyPI here.
#
{
  pkgs,
  lib,
  python,
}:
let
  py = python.pkgs;
in
py.buildPythonPackage rec {
  pname = "tqdm-loggable";
  version = "0.4.1";
  pyproject = true;

  src = pkgs.fetchPypi {
    pname = "tqdm_loggable";
    inherit version;
    hash = "sha256-SRI//LLeuUjttxIdfgmmAIkU4NAzMVTwYOQ13rqeVHo=";
  };

  build-system = [ py.poetry-core ];

  dependencies = [ py.tqdm ];

  pythonImportsCheck = [ "tqdm_loggable" ];

  meta = {
    description = "Better progress bar logging for tqdm in non-interactive environments";
    homepage = "https://github.com/tradingstrategy-ai/tqdm-loggable";
    license = lib.licenses.mit;
  };
}
