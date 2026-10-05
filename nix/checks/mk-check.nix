#
# nix/checks/mk-check.nix — runpod-flash
#
# Helper that turns a check into a shellchecked `writeShellApplication` plus a
# one-line runner. All the real logic (staging the scoped source, exporting
# env, invoking the tool) lives in the application `text`, so:
#
#   - shellcheck runs over it at build time (writeShellApplication's default
#     checkPhase) — the correctness the plain `runCommand "...''<blob>''"` idiom
#     lacks;
#   - `set -o errexit -o nounset -o pipefail` is applied, so `|| exit 1` guards
#     are unnecessary and a failing command aborts the check;
#   - PATH is exactly `runtimeInputs` (+ the stdenv build tools), so the check
#     can't silently depend on something ambient.
#
# A flake check has to *run* at build time, which `writeShellApplication` alone
# does not (it only writes the script). The `runCommand` runner is therefore
# reduced to invoking the app and touching `$out` — the two lines that must be
# a build, with no check logic in them.
#
{ pkgs, lib }:
{
  name,
  src,
  runtimeInputs ? [ ],
  text,
}:
let
  app = pkgs.writeShellApplication {
    inherit name runtimeInputs;
    text = ''
      # Stage a writable copy of the (fileset-scoped) source and run there.
      work="$(mktemp -d)"
      cp -r ${src}/. "$work/s"
      chmod -R +w "$work/s"
      cd "$work/s"

      ${text}
    '';
  };
in
pkgs.runCommand name { } ''
  ${lib.getExe app}
  touch "$out"
''
