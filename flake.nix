{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = {
    nixpkgs,
    flake-utils,
    ...
  }:
    flake-utils.lib.eachDefaultSystem (
      system: let
        pkgs = import nixpkgs {
          system = system;
        };
        systemd-control-api = pkgs.callPackage ./systemd-control-api.nix {};
      in {
        defaultPackage = systemd-control-api;
        packages = {
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
