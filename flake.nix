{
  description = "nixplain — explain Nix configs to agents";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    crane.url = "github:ipetkov/crane";
  };

  outputs = { self, nixpkgs, crane }:
    let
      supportedSystems = [ "x86_64-linux" "aarch64-linux" "x86_64-darwin" "aarch64-darwin" ];
      forAllSystems = f: nixpkgs.lib.genAttrs supportedSystems (system: f {
        pkgs = nixpkgs.legacyPackages.${system};
      });
    in
    {
      packages = forAllSystems ({ pkgs }:
        let
          isDarwin = pkgs.stdenv.isDarwin;
          isLinux = pkgs.stdenv.isLinux;
          craneLib = crane.mkLib pkgs;
          gpuFeatures = if isDarwin then [ "metal" ] else [ "vulkan" ];
          gpuFeaturesStr = builtins.concatStringsSep "," gpuFeatures;

          toon-format = pkgs.python3Packages.buildPythonPackage {
            pname = "toon-format";
            version = "0.9.0b1";
            format = "wheel";
            src = pkgs.fetchurl {
              url = "https://files.pythonhosted.org/packages/63/f3/27ab1d982bb81bf9ac5be70b4c774996eb8562b93c77e93c253c22be951f/toon_format-0.9.0b1-py3-none-any.whl";
              hash = "sha256-7+7pGVAfkRN/AX977TR4nAZ/dheBEaqHKkm8hlPc474=";
            };
          };

          # nix-why Rust build
          nix-why-src = pkgs.lib.cleanSourceWith {
            src = ./nix-why;
            filter = path: type:
              (builtins.match ".*\.(txt|toml)$" path != null) ||
              (craneLib.filterCargoSources path type);
          };

          nix-why-common = {
            src = nix-why-src;
            pname = "nix-why";
            version = "0.1.0";
            strictDeps = true;
            nativeBuildInputs = with pkgs; [
              pkg-config cmake rustPlatform.bindgenHook
            ] ++ (if isLinux then [ pkgs.shaderc ] else []);
            buildInputs = with pkgs; [ openssl ]
              ++ (if isDarwin then [ pkgs.apple-sdk_15 pkgs.darwin.cctools ]
                  else [ pkgs.vulkan-headers pkgs.vulkan-loader pkgs.shaderc pkgs.glslang ]);
            LIBCLANG_PATH = "${pkgs.llvmPackages.libclang.lib}/lib";
            cargoExtraArgs = "--features ${gpuFeaturesStr}";
          };

          nix-why-deps = craneLib.buildDepsOnly nix-why-common;

          nix-why-cli = craneLib.buildPackage (nix-why-common // {
            cargoArtifacts = nix-why-deps;
            doCheck = false;
            preBuild = ''
              rm -rf target/release/build/llama-cpp-sys-2-* 2>/dev/null || true
              rm -rf target/debug/build/llama-cpp-sys-2-* 2>/dev/null || true
            '';
          });

          # Model definitions
          models = {
            qwen2_5-coder = {
              name = "qwen2.5-coder-0.5b-instruct-q8_0.gguf";
              url = "https://huggingface.co/Qwen/Qwen2.5-Coder-0.5B-Instruct-GGUF/resolve/main/qwen2.5-coder-0.5b-instruct-q8_0.gguf";
              sha256 = "1la4ndkiywa6swigj60y4xpsxd0zr3p270l747qi5m4pz8hpg9z1";
              family = "qwen";
            };
            smollm2 = {
              name = "SmolLM2-135M-Instruct-Q8_0.gguf";
              url = "https://huggingface.co/bartowski/SmolLM2-135M-Instruct-GGUF/resolve/main/SmolLM2-135M-Instruct-Q8_0.gguf";
              sha256 = "10xsdfq2wx0685kd7xx9hw4xha0jkcdmi60xqlf784vrdxqra4ss";
              family = "smollm";
            };
          };

          mkEmbeddedNixWhy = { model, pname ? "nix-why" }:
            let modelFile = pkgs.fetchurl { url = model.url; sha256 = model.sha256; };
            in pkgs.stdenv.mkDerivation {
              inherit pname;
              version = "0.1.0";
              dontUnpack = true;
              dontStrip = true;
              nativeBuildInputs = [ pkgs.python3 ];
              buildPhase = ''
                BINARY_SIZE=$(stat -f%z ${nix-why-cli}/bin/nix-why 2>/dev/null || stat -c%s ${nix-why-cli}/bin/nix-why)
                MODEL_SIZE=$(stat -f%z ${modelFile} 2>/dev/null || stat -c%s ${modelFile})
                cat ${nix-why-cli}/bin/nix-why > nix-why-embedded
                cat ${modelFile} >> nix-why-embedded
                python3 -c "
import struct, sys
offset = $BINARY_SIZE
size = $MODEL_SIZE
family_map = {'qwen': 0, 'gemma': 1, 'smollm': 2}
family = family_map.get('${model.family}', 0)
trailer = b'WHYMODEL' + struct.pack('<Q', offset) + struct.pack('<Q', size) + struct.pack('<B', family)
sys.stdout.buffer.write(trailer)
                " >> nix-why-embedded
                chmod +x nix-why-embedded
              '';
              installPhase = ''
                mkdir -p $out/bin
                cp nix-why-embedded $out/bin/nix-why
              '';
            };

        in {
        default = pkgs.python3Packages.buildPythonApplication {
          pname = "nixplain";
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

        nixplain = self.packages.${pkgs.stdenv.hostPlatform.system}.default;

        # nix-why: bare CLI (bring your own model)
        nix-why-cli = nix-why-cli;

        # nix-why: embedded with Qwen2.5-Coder (530MB)
        nix-why = mkEmbeddedNixWhy { model = models.qwen2_5-coder; };

        # nix-why: embedded with SmolLM2 (145MB, fast)
        nix-why-smol = mkEmbeddedNixWhy {
          model = models.smollm2;
          pname = "nix-why-smol";
        };
      });

      devShells = forAllSystems ({ pkgs }: {
        default = pkgs.mkShell {
          packages = [
            (pkgs.python3.withPackages (ps: [
              ps.click ps.pytest ps.tree-sitter
              ps.tree-sitter-grammars.tree-sitter-nix
            ]))
            pkgs.python3Packages.pip
            pkgs.nixf
          ];
          env.PYTHONPATH = "src";
          shellHook = ''
            pip install --quiet toon-format==0.9.0b1 2>/dev/null || true
          '';
        };
      });
    };
}
