{pkgs, ...}: {
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
  Commented until proper refactoring

  git-hooks.hooks = {
    trim-trailing-whitespace.enable = true;
    end-of-file-fixer.enable = true;
    check-yaml.enable = true;

    ruff.enable = true;
    ruff-format.enable = true;

    mypy.enable = true;
  };
  */
}
