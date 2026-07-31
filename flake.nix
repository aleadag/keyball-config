{
  description = "Pinned Keyball configuration toolchain";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";

  outputs =
    { nixpkgs, ... }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs { inherit system; };
      inherit (pkgs) lib;
      vitaly = pkgs.callPackage ./nix/vitaly.nix { };
      vialConverter = pkgs.callPackage ./nix/vial-converter.nix { };
      python = pkgs.python3;
      testPython = python.withPackages (packages: [ packages.pyyaml ]);
      keymap = pkgs.keymap-drawer;

      sourceRoots = [
        ".github"
        "config"
        "keyball_config"
        "scripts"
        "tests"
        "keyball39.vil"
        "keyball44.vil"
      ];
      excludedSourceNames = [
        ".cache"
        ".mypy_cache"
        ".pytest_cache"
        "__pycache__"
        "build"
        "result"
        "results"
      ];
      projectSource = lib.cleanSourceWith {
        src = ./.;
        filter =
          path: _type:
          let
            root = toString ./.;
            fullPath = toString path;
            relativePath = lib.removePrefix "${root}/" fullPath;
            pathParts = lib.splitString "/" relativePath;
            topLevel = builtins.head pathParts;
            fileName = builtins.baseNameOf fullPath;
          in
          fullPath == root
          || (
            builtins.elem topLevel sourceRoots
            && !lib.any (part: builtins.elem part excludedSourceNames) pathParts
            && !lib.hasSuffix ".log" fileName
            && !lib.hasSuffix ".pyc" fileName
          );
      };

      renderEnvironment = ''
        export KEYBALL_CONVERTER=${lib.getExe vialConverter}
        export KEYBALL_KEYMAP=${lib.getExe keymap}
        export KEYBALL_GEOMETRY_ROOT=${vialConverter}/share/keyball-geometry
        export LC_ALL=C.UTF-8
        export LANG=C.UTF-8
        export TZ=UTC
        export SOURCE_DATE_EPOCH=0
      '';

      keyballConfig = pkgs.writeShellApplication {
        name = "keyball-config";
        runtimeInputs = [
          pkgs.git
          python
          vitaly
          vialConverter
          keymap
        ];
        text = ''
          ${renderEnvironment}
          export PYTHONPATH=${projectSource}
          exec ${lib.getExe python} -m keyball_config.cli "$@"
        '';
      };
      commandApp =
        name: command:
        pkgs.writeShellApplication {
          inherit name;
          runtimeInputs = [ keyballConfig ];
          text = ''
            exec keyball-config ${command} "$@"
          '';
        };
      backupApp = commandApp "keyball-backup" "backup";
      renderApp = commandApp "keyball-render" "render";
      siteApp = commandApp "keyball-site" "site";
      validateSiteApp = commandApp "keyball-validate-site" "validate-site";

      site =
        pkgs.runCommand "keyball-config-site"
          {
            nativeBuildInputs = [
              python
              vialConverter
              keymap
            ];
          }
          ''
            ${renderEnvironment}
            cd ${projectSource}
            ${lib.getExe python} -m keyball_config.cli site --output "$TMPDIR/site"
            ${lib.getExe python} -m keyball_config.cli validate-site "$TMPDIR/site"
            mkdir "$out"
            cp -a "$TMPDIR/site/." "$out/"
            ${lib.getExe python} -m keyball_config.cli validate-site "$out"
          '';

      unitTests =
        pkgs.runCommand "keyball-config-unit-tests"
          {
            nativeBuildInputs = [ testPython ];
          }
          ''
            export LC_ALL=C.UTF-8
            export LANG=C.UTF-8
            export TZ=UTC
            export SOURCE_DATE_EPOCH=0
            cd ${projectSource}
            ${lib.getExe testPython} -m unittest discover -s tests -v
            ${lib.getExe testPython} scripts/generate_vitaly_v6_keycodes.py \
              --source ${vitaly.src.outPath}/src/keycodes/v6/code_to_name.rs \
              --check
            touch "$out"
          '';

      conversionTests =
        pkgs.runCommand "keyball-config-conversion-tests"
          {
            nativeBuildInputs = [
              python
              vialConverter
              keymap
            ];
          }
          ''
            ${renderEnvironment}
            cd ${projectSource}
            ${lib.getExe python} -m unittest \
              tests.test_keymap.RealRenderingIntegrationTests -v
            touch "$out"
          '';

      siteContractTests =
        pkgs.runCommand "keyball-config-site-contract-tests"
          {
            nativeBuildInputs = [
              python
              vialConverter
              keymap
            ];
          }
          ''
            ${renderEnvironment}
            cd ${projectSource}
            test -f keyball44.vil
            test ! -e .git
            test ! -e .beads
            test ! -e .internal
            test ! -e .worktrees
            test ! -e build
            test ! -e result
            test ! -e results
            test -z "$(find . -type f \( -name '*.log' -o -name '*.pyc' \) -print -quit)"
            ${lib.getExe python} -m unittest \
              tests.test_site.RealSiteIntegrationTests -v
            cp -a ${site} "$TMPDIR/realized-site"
            ${lib.getExe python} -m keyball_config.cli validate-site "$TMPDIR/realized-site"
            test -f ${site}/index.html
            test -s ${site}/keyball44.svg
            test -z "$(find ${site} -type l -print -quit)"
            test -z "$(find ${site} -type f \
              \( -name '*.vil' -o -name '*.yaml' -o -name '*.yml' \) -print -quit)"
            touch "$out"
          '';

      workflowChecks =
        pkgs.runCommand "keyball-config-workflow-checks"
          {
            nativeBuildInputs = [
              pkgs.actionlint
              testPython
            ];
          }
          ''
            mkdir -p "$TMPDIR/actionlint-project/.git"
            cp -r ${projectSource}/.github "$TMPDIR/actionlint-project/.github"
            cd "$TMPDIR/actionlint-project"
            actionlint
            cd ${projectSource}
            ${lib.getExe testPython} -m unittest tests.test_workflow -v
            touch "$out"
          '';
    in
    {
      formatter.${system} = pkgs.nixfmt-tree;

      devShells.${system}.default = pkgs.mkShell {
        packages = [
          pkgs.actionlint
          pkgs.git
          testPython
          vitaly
          vialConverter
          keymap
          keyballConfig
        ];
      };

      apps.${system} = {
        backup = {
          type = "app";
          program = "${backupApp}/bin/keyball-backup";
          meta.description = "Safely back up the sole connected supported Keyball";
        };
        render = {
          type = "app";
          program = "${renderApp}/bin/keyball-render";
          meta.description = "Render all present Keyball backups";
        };
        site = {
          type = "app";
          program = "${siteApp}/bin/keyball-site";
          meta.description = "Build the complete Keyball keymap site";
        };
        validate-site = {
          type = "app";
          program = "${validateSiteApp}/bin/keyball-validate-site";
          meta.description = "Validate a copied Keyball site artifact";
        };
      };

      packages.${system} = {
        inherit
          keyballConfig
          site
          vitaly
          vialConverter
          ;
        default = site;
      };

      checks.${system} = {
        unit = unitTests;
        conversion = conversionTests;
        site = siteContractTests;
        workflow = workflowChecks;
      };
    };
}
