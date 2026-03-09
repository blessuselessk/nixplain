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
      packages = forAllSystems ({ pkgs }:
        let
          toon-format = pkgs.python3Packages.buildPythonPackage {
            pname = "toon-format";
            version = "0.9.0b1";
            format = "wheel";
            src = pkgs.fetchurl {
              url = "https://files.pythonhosted.org/packages/63/f3/27ab1d982bb81bf9ac5be70b4c774996eb8562b93c77e93c253c22be951f/toon_format-0.9.0b1-py3-none-any.whl";
              hash = "sha256-7+7pGVAfkRN/AX977TR4nAZ/dheBEaqHKkm8hlPc474=";
            };
          };
        in {
        default = pkgs.python3Packages.buildPythonApplication {
          pname = "hatc";
          version = "0.1.0";
          pyproject = true;

          src = ./.;

          build-system = [ pkgs.python3Packages.setuptools ];
          dependencies = [ pkgs.python3Packages.click toon-format ];

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
            pkgs.python3Packages.pip
          ];
          env.PYTHONPATH = "src";
          shellHook = ''
            pip install --quiet toon-format==0.9.0b1 2>/dev/null || true
          '';
        };
      });
    };
}
