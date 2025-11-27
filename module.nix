{
  config,
  lib,
  pkgs,
  ...
}:
with lib; let
  cfg = config.services.systemd-control-api;

  # Generate polkit rules for the configured services
  serviceNames = map (s: s.service) cfg.services;

  # Build polkit condition for exact service names
  serviceConditions =
    concatMapStringsSep " || " (
      service: "action.lookup(\"unit\") == \"${service}\""
    )
    serviceNames;

  # Build polkit condition for service patterns
  patternConditions =
    concatMapStringsSep " || " (
      pattern: "action.lookup(\"unit\").startsWith(\"${pattern}\")"
    )
    cfg.servicePatterns;

  # Combine all conditions
  allConditions =
    if serviceConditions != "" && patternConditions != ""
    then "${serviceConditions} || ${patternConditions}"
    else if serviceConditions != ""
    then serviceConditions
    else patternConditions;

  # Convert services list to JSON for the Python script
  servicesJson = builtins.toJSON cfg.services;
in {
  options.services.systemd-control-api = {
    enable = mkEnableOption "systemd control API service";

    package = mkOption {
      type = types.package;
      default = pkgs.callPackage ./systemd-control-api.nix {};
      description = "The systemd-control-api package to use";
    };

    port = mkOption {
      type = types.port;
      default = 8080;
      description = "Port for the API server to listen on";
    };

    environmentFile = mkOption {
      type = types.nullOr types.path;
      default = null;
      example = "/run/secrets/systemd-control-api";
      description = ''
        Path to an environment file containing secrets.
        This file is not added to the nix store, so it can be used to pass secrets.
        The file should contain:
        ```
        SYSTEMD_CONTROL_API_KEY=your-super-secure-api-key-here
        ```
      '';
    };

    user = mkOption {
      type = types.str;
      default = "systemd-control-api";
      description = "User account under which the API service runs";
    };

    group = mkOption {
      type = types.str;
      default = "systemd-control-api";
      description = "Group under which the API service runs";
    };

    services = mkOption {
      type = types.listOf (types.submodule {
        options = {
          service = mkOption {
            type = types.str;
            description = "Systemd service name (e.g., nginx.service)";
            example = "nginx.service";
          };

          displayName = mkOption {
            type = types.str;
            description = "Human-readable name for the service";
            example = "Web Server";
          };

          description = mkOption {
            type = types.str;
            description = "Description of the service";
            example = "Main nginx web server";
          };

          metadata = mkOption {
            type = types.attrs;
            default = {};
            description = "Additional metadata to include in API responses (arbitrary key-value pairs)";
            example = literalExpression ''
              {
                port = "80";
                type = "web";
                environment = "production";
              }
            '';
          };
        };
      });
      default = [];
      description = "List of systemd services to expose via the API";
      example = literalExpression ''
        [
          {
            service = "nginx.service";
            displayName = "Web Server";
            description = "Main nginx web server";
            metadata = {
              port = "80";
              type = "web";
            };
          }
          {
            service = "postgresql.service";
            displayName = "Database";
            description = "PostgreSQL database server";
            metadata = {
              version = "15";
            };
          }
        ]
      '';
    };

    servicePatterns = mkOption {
      type = types.listOf types.str;
      default = [];
      description = ''
        Additional service name patterns to allow in polkit rules.
        Useful for matching multiple services with common prefixes.
        Each pattern should be a service name prefix (e.g., "myapp-" will match "myapp-worker.service").
      '';
      example = ["worker-"];
    };

    security = {
      allowedHosts = mkOption {
        type = types.listOf types.str;
        default = [];
        description = ''          List of allowed client IPs or hostnames for host-based access control.
          Supports exact IPs, CIDR notation (e.g., "192.168.1.0/24"), and "localhost".
          If empty, only API key authentication is used.
          If set, clients must match both the API key (if configured) AND be in this list.
          Can also be set via SYSTEMD_CONTROL_API_ALLOWED_HOSTS in the environment file.
        '';
        example = ["localhost" "192.168.1.0/24" "10.0.0.50"];
      };
    };

    openFirewall = mkOption {
      type = types.bool;
      default = false;
      description = "Whether to open the API port in the firewall";
    };
  };

  config = mkIf cfg.enable {
    assertions = [
      {
        assertion = cfg.environmentFile != null || cfg.security.allowedHosts != [];
        message = "services.systemd-control-api: At least one security method must be configured - set environmentFile (containing SYSTEMD_CONTROL_API_KEY) and/or security.allowedHosts";
      }
      {
        assertion = cfg.services != [];
        message = "services.systemd-control-api.services must not be empty";
      }
    ];

    # Create dedicated user and group for the service
    users = mkIf (cfg.user == "systemd-control-api") {
      users.${cfg.user} = {
        isSystemUser = true;
        group = cfg.group;
        description = "Systemd Control API service user";
      };
      groups.${cfg.group} = {};
    };

    # Polkit rule to allow the API user to control specified services
    security.polkit.extraConfig = mkIf (allConditions != "") ''
      polkit.addRule(function(action, subject) {
        if (action.id == "org.freedesktop.systemd1.manage-units" &&
            subject.user == "${cfg.user}" &&
            (${allConditions})) {
          return polkit.Result.YES;
        }
      });
    '';

    # Create systemd service for the API
    systemd.services.systemd-control-api = {
      description = "Systemd Control API";
      after = ["network.target"];
      wantedBy = ["multi-user.target"];

      environment =
        {
          SYSTEMD_CONTROL_API_PORT = toString cfg.port;
          SYSTEMD_CONTROL_API_SERVICES = servicesJson;
        }
        // (
          if cfg.security.allowedHosts != []
          then {
            SYSTEMD_CONTROL_API_ALLOWED_HOSTS = concatStringsSep "," cfg.security.allowedHosts;
          }
          else {}
        );

      serviceConfig = {
        Type = "simple";
        User = cfg.user;
        Group = cfg.group;
        ExecStart = "${cfg.package}/bin/systemd-control-api";
        Restart = "always";
        RestartSec = "10s";
        EnvironmentFile = mkIf (cfg.environmentFile != null) cfg.environmentFile;

        # Security settings
        PrivateTmp = true;
        ProtectSystem = "strict";
        ProtectHome = true;
        NoNewPrivileges = false; # Required for polkit to work
      };
    };

    # Open firewall port if requested
    networking.firewall.allowedTCPPorts = mkIf cfg.openFirewall [cfg.port];
  };
}
