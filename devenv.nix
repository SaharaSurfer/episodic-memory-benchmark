{
  pkgs,
  lib,
  config,
  ...
}: let
  patchelf = lib.getExe pkgs.patchelf;
  ruffExe = "${config.devenv.root}/.venv/bin/ruff";
  mypyExe = "${config.devenv.root}/.venv/bin/mypy";
  pytestExe = "${config.devenv.root}/.venv/bin/pytest";
in {
  languages.python = {
    enable = true;
    package = pkgs.python312;

    poetry = {
      enable = true;
      package = pkgs.poetry;

      activate.enable = true;
      install = {
        enable = true;
        groups = ["main" "dev"];
      };
    };
  };

  /*
  Python packages come from poetry so people on other distros get exactly
  the same versions. The hooks below run ruff and mypy from .venv too, so
  each tool exists once. The problem is that NixOS can't run the venv's
  ruff without patching, so that's what we do below.
  */
  tasks."venv:patch-ruff" = {
    exec = ''
      ${patchelf} \
        --set-interpreter ${pkgs.stdenv.cc.bintools.dynamicLinker} \
        --set-rpath ${lib.makeLibraryPath [pkgs.stdenv.cc.cc]} \
        ${ruffExe}
    '';
    status = ''
      ${patchelf} --print-interpreter ${ruffExe} \
        | ${lib.getExe pkgs.gnugrep} -q '^/nix/store/'
    '';
    after = ["devenv:python:poetry"];
    before = ["devenv:enterShell" "devenv:git-hooks:run"];
  };

  tasks."tests:pytest" = {
    exec = pytestExe;
    after = ["devenv:git-hooks:run"];
    before = ["devenv:enterTest"];
  };

  scripts.mutation-run = {
    exec = ''
      cd ${config.devenv.root}
      rm -rf mutants
      ${config.devenv.root}/.venv/bin/mutmut run
      ${config.devenv.root}/.venv/bin/mutmut results
    '';
    description = "Mutation-test the legality and folds modules from clean";
  };

  git-hooks.hooks = {
    trim-trailing-whitespace.enable = true;
    end-of-file-fixer.enable = true;
    check-yaml.enable = true;

    ruff = {
      enable = true;
      package = null;
      entry = "${ruffExe} check --fix";
    };
    ruff-format = {
      enable = true;
      package = null;
      entry = "${ruffExe} format";
    };
    mypy = {
      enable = true;
      package = null;
      entry = "${mypyExe}";
      pass_filenames = false;
    };
  };
}
