#
# flake.nix — runpod-flash
#
# Thin orchestrator. Every concern lives under ./nix/ and is wired up here.
# See ./nix/default.nix for the per-system aggregator.
#
# Quick references:
#   nix develop                 # dev shell (Python 3.14: ruff, mypy, bandit, ...)
#   nix flake check             # hermetic checks: ruff lint + format, nixfmt, shellcheck, pytest
#   nix build   .#default       # build the flash CLI
#   nix run     .#default -- --help
#   nix profile install github:runpod/flash
#
{
  description = "runpod-flash — Python SDK for distributed inference and serving on Runpod serverless";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs =
    {
      self,
      nixpkgs,
      flake-utils,
    }:
    flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = import nixpkgs { inherit system; };
        lib = nixpkgs.lib;

        aggregator = import ./nix {
          inherit pkgs lib;
          src = ./.;
        };
      in
      {
        inherit (aggregator)
          packages
          devShells
          checks
          apps
          ;
      }
    );
}
