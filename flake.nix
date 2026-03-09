{
  description = "HATC — Human-Agent Teaming Comments toolchain";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      supportedSystems = [ "x86_64-linux" "aarch64-linux" "x86_64-darwin" "aarch64-darwin" ];
      forAllSystems = f: nixpkgs.lib.genAttrs supportedSystems (system: f {
        pkgs = nixpkgs.legacyPackages.${system};
      });
    in
    {
      packages = forAllSystems ({ pkgs }: {
        default = pkgs.python3Packages.buildPythonApplication {
          pname = "hatc";
          version = "0.1.0";
          pyproject = true;

          src = ./.;

          build-system = [ pkgs.python3Packages.setuptools ];
          dependencies = [ pkgs.python3Packages.click ];

          nativeCheckInputs = [ pkgs.python3Packages.pytest ];
          checkPhase = ''
            pytest tests/
          '';
        };

        hatc = self.packages.${pkgs.stdenv.hostPlatform.system}.default;
      });

      devShells = forAllSystems ({ pkgs }: {
        default = pkgs.mkShell {
          packages = [
            (pkgs.python3.withPackages (ps: [ ps.click ps.pytest ]))
          ];
          env.PYTHONPATH = "src";
        };
      });
    };
}
