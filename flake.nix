{
  description = "uv2nix Flake for DeerFlow";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-parts.url = "github:hercules-ci/flake-parts";

    # The three uv2nix building blocks
    pyproject-nix.url = "github:pyproject-nix/pyproject.nix";
    pyproject-build-systems.url = "github:pyproject-nix/build-system-pkgs";
    uv2nix.url = "github:pyproject-nix/uv2nix";
  };

  outputs = inputs @ {
    flake-parts,
    nixpkgs,
    ...
  }:
    flake-parts.lib.mkFlake {inherit inputs;} {
      imports = [flake-parts.flakeModules.easyOverlay];

      systems = ["x86_64-linux" "aarch64-linux" "x86_64-darwin" "aarch64-darwin"];

      perSystem = {
        self',
        system,
        pkgs,
        lib,
        ...
      }: let
        python = pkgs.python312;
        workspace = inputs.uv2nix.lib.workspace.loadWorkspace {workspaceRoot = ./.;};
        # Prefer pre-built wheels for speed.
        # If a package no longer ships a wheel for your Python version,
        #   – switch to "sdist" to build from source, OR
        #   – keep "wheel" and pull from your own binary cache (Cachix, Hydra, …).
        overlay = workspace.mkPyprojectOverlay {sourcePreference = "wheel";};

        baseSet = pkgs.callPackage inputs.pyproject-nix.build.packages {inherit python;};

        # Custom overrides for sdists that require the legacy setuptools.
        # These only apply when the builder falls back to an sdist build.
        pyprojectOverrides = final: prev: rec {
          # helper that injects the legacy build-system
          _legacy = bs: (final.resolveBuildSystem bs);

          sgmllib3k = prev.sgmllib3k.overrideAttrs (old: {
            nativeBuildInputs =
              (old.nativeBuildInputs or [])
              ++ [
                (_legacy {
                  setuptools = [];
                  wheel = [];
                })
              ];
          });

          peewee = prev.peewee.overrideAttrs (old: {
            nativeBuildInputs =
              (old.nativeBuildInputs or [])
              ++ [
                (_legacy {
                  setuptools = [];
                  wheel = [];
                })
              ];
          });
        };

        pythonSet =
          baseSet.overrideScope
          (lib.composeManyExtensions [
            inputs.pyproject-build-systems.overlays.default
            overlay
            pyprojectOverrides
          ]);
        
        # Build a fully-deterministic virtual-env named "venv" containing only the deps in workspace.deps.default
        venv = pythonSet.mkVirtualEnv "venv" workspace.deps.default;
        
        # Choose Node.js 22 for the web UI
        node = pkgs.nodejs_22;
        
        # Override pnpm to use that same Node.js interpreter
        pnpm = pkgs.pnpm.override {nodejs = node;};


        # Common toolkit for all shells:
        # - uv          (Python env manager)
        # - the venv    (interpreter + all locked Python deps)
        # - marp-cli    (for PPT generation)
        # - node + pnpm (for building the frontend)
        commonPkgs = [pkgs.uv venv pkgs.marp-cli node pnpm];
      in {
        overlayAttrs = pythonSet.overlay;

        devShells.common = pkgs.mkShell {packages = commonPkgs;};

        devShells.default = pkgs.mkShell {
          packages = commonPkgs ++ [pkgs.git];
          shellHook = ''
            export UV_PYTHON_DOWNLOADS=never
            export UV_PYTHON="${venv}/bin/python"
            export SSL_CERT_FILE="${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
            unset PYTHONPATH
          '';
        };
      };
    };
}
