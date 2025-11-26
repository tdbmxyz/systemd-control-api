# Systemd Control API - NixOS Module

An HTTP API for controlling systemd services.

## Installation (NixOS)

### As a Flake Input

Add to your `flake.nix`:

```nix
{
  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
    systemd-control-api.url = "path:/projects/nix/systemd-control-api";
    # or from a git repository:
    # systemd-control-api.url = "github:yourusername/systemd-control-api";
  };

  outputs = { self, nixpkgs, systemd-control-api, ... }: {
    nixosConfigurations.yourhost = nixpkgs.lib.nixosSystem {
      modules = [
        systemd-control-api.nixosModules.default
        ./configuration.nix
      ];
    };
  };
}
```

## Usage

### Basic Configuration

```nix
{
  services.systemd-control-api = {
    enable = true;

    # API server configuration
    port = 8091;

    # Path to environment file containing SYSTEMD_CONTROL_API_KEY
    environmentFile = "/run/secrets/systemd-control-api";

    # Services to expose via the API
    services = [
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
    ];
  };
}
```

### Advanced Configuration

```nix
{
  services.systemd-control-api = {
    enable = true;
    port = 8091;

    # Path to environment file containing secrets
    # The file should contain: SYSTEMD_CONTROL_API_KEY=your-super-secure-api-key-here
    environmentFile = "/run/secrets/systemd-control-api";

    # Custom user/group for the API service
    user = "api-controller";
    group = "api-controller";

    # Additional service patterns to allow in polkit
    # Useful if your services follow naming patterns
    servicePatterns = [
      "myapp-*"
      "worker-*"
    ];

    # Services with rich metadata
    services = [
      {
        service = "myapp-backend.service";
        displayName = "MyApp Backend";
        description = "Backend service for MyApp";
        metadata = {
          environment = "production";
          version = "2.3.1";
        };
      }
    ]
  };
}
```

## API Endpoints

### GET `/services`

Get status of all configured services.

**Headers:**
```
Authorization: Bearer your-super-secure-api-key-here
```

**Response:**
```json
{
  "last_updated": "2025-11-26T10:30:00",
  "services": [
    {
      "service": "nginx.service",
      "display_name": "Web Server",
      "description": "Main nginx web server",
      "status": "active",
      "enabled": true,
      "metadata": {
        "port": "80",
        "type": "web"
      }
    }
  ]
}
```

### POST `/service/{service_name}/{action}`

Control a service (start, stop, restart).

**Headers:**
```
Authorization: Bearer your-super-secure-api-key-here
```

**Actions:** `start`, `stop`, `restart`

**Example:**
```bash
curl -X POST \
  -H "Authorization: Bearer your-super-secure-api-key-here" \
  http://localhost:8091/service/nginx.service/restart
```

**Response:**
```json
{
  "success": true,
  "message": "Service restart successful",
  "display_name": "Web Server"
}
```

## Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enable` | bool | `false` | Enable the systemd control API |
| `port` | int | `8091` | Port for the API server |
| `environmentFile` | path | *required* | Path to file containing `SYSTEMD_CONTROL_API_KEY=<secret>` |
| `user` | string | `"systemd-control-api"` | User to run the API service |
| `group` | string | `"systemd-control-api"` | Group for the API service |
| `services` | list | `[]` | List of services to expose |
| `servicePatterns` | list | `[]` | Additional service name patterns for polkit |

### Service Definition

Each service in the `services` list should have:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `service` | string | yes | Systemd service name (e.g., "nginx.service") |
| `displayName` | string | yes | Human-readable name |
| `description` | string | yes | Service description |
| `metadata` | attrs | no | Custom metadata (arbitrary key-value pairs) |

## Security Considerations

1. **API Key**: Always use a strong API key stored in the environment file (not in the Nix store)
2. **Environment File**: Use proper file permissions (e.g., `chmod 600`) and ownership for the secrets file
3. **Firewall**: Consider restricting API access to specific networks
4. **Polkit Rules**: The module only grants control over explicitly configured services
5. **HTTPS**: Use a reverse proxy (like Traefik) for HTTPS in production
