{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = {
    self,
    nixpkgs,
    flake-utils,
    ...
  }:
    {
      # NixOS module (system-independent)
      nixosModules = {
        default = self.nixosModules.systemd-control-api;
        systemd-control-api = import ./module.nix;
      };
    }
    // flake-utils.lib.eachDefaultSystem (
      system: let
        pkgs = import nixpkgs {
          system = system;
        };
        systemd-control-api = pkgs.callPackage ./systemd-control-api.nix {};
      in {
        packages = {
          default = systemd-control-api;
          systemd-control-api = systemd-control-api;
        };
        devShells = {
          default = pkgs.mkShell {
            packages = [systemd-control-api];
          };
          systemd-control-api = pkgs.mkShell {
            packages = [systemd-control-api];
          };
        };
      }
    );
}
