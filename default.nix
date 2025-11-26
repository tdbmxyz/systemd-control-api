{pkgs ? import <nixpkgs> {}}:
pkgs.callPackage ./systemd-control-api.nix {}
