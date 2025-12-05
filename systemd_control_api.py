#!/usr/bin/env python3
"""
Systemd Control API Server
Provides HTTP API endpoints for monitoring and controlling systemd services
"""

import json
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from ipaddress import ip_address, ip_network
from typing import Any

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from systemd import journal


# =============================================================================
# Configuration
# =============================================================================


@dataclass
class Config:
    """Application configuration"""

    api_key: str | None
    port: int
    services: list[dict]
    allowed_hosts: list[str]  # Empty list means no host restriction

    @property
    def has_api_key(self) -> bool:
        """Check if API key authentication is configured"""
        return bool(self.api_key)

    @property
    def has_host_restriction(self) -> bool:
        """Check if host-based restriction is configured"""
        return len(self.allowed_hosts) > 0


def get_config() -> Config:
    """Get configuration from environment variables"""
    api_key = os.environ.get("SYSTEMD_CONTROL_API_KEY")  # None if not set
    port = int(os.environ.get("SYSTEMD_CONTROL_API_PORT", "8080"))

    services_json = os.environ.get("SYSTEMD_CONTROL_API_SERVICES", "[]")
    try:
        services = json.loads(services_json)
    except json.JSONDecodeError:
        raise ValueError("SYSTEMD_CONTROL_API_SERVICES must be valid JSON")

    # Allowed hosts (comma-separated list of IPs or hostnames)
    # Empty string or unset means no host restriction
    allowed_hosts_str = os.environ.get("SYSTEMD_CONTROL_API_ALLOWED_HOSTS", "")
    allowed_hosts = [h.strip() for h in allowed_hosts_str.split(",") if h.strip()]

    config = Config(
        api_key=api_key,
        port=port,
        services=services,
        allowed_hosts=allowed_hosts,
    )

    # Note: Both security methods are optional
    # If neither is configured, the API is accessible without authentication
    # This is suitable for deployments behind a reverse proxy

    # Debug logging for security configuration
    journal.send(
        f"systemd-control-api: Security config - API key: {config.has_api_key}, Host restriction: {config.has_host_restriction} ({len(config.allowed_hosts)} hosts)",
        PRIORITY=journal.LOG_INFO,
        SYSLOG_IDENTIFIER="systemd-control-api",
    )

    return config


# =============================================================================
# Pydantic Models
# =============================================================================


class ServiceAction(str, Enum):
    start = "start"
    stop = "stop"
    restart = "restart"


class ServiceStatus(BaseModel):
    service: str
    display_name: str
    description: str
    status: str
    enabled: bool
    metadata: dict[str, Any] | None = None


class ServicesResponse(BaseModel):
    last_updated: str
    services: list[ServiceStatus]


class HealthResponse(BaseModel):
    status: str
    timestamp: str
    services_count: int


class ServiceControlResponse(BaseModel):
    success: bool
    message: str
    display_name: str


class ErrorResponse(BaseModel):
    detail: str


# =============================================================================
# Systemd Integration (using python-systemd)
# =============================================================================


def get_service_status_via_dbus(service_name: str) -> dict[str, Any]:
    """Get the status of a systemd service using D-Bus via python-systemd"""
    try:
        from pydbus import SystemBus

        bus = SystemBus()
        systemd = bus.get(".systemd1")

        try:
            unit_path = systemd.GetUnit(service_name)
            unit = bus.get(".systemd1", unit_path)

            active_state = unit.ActiveState
            unit_file_state = unit.UnitFileState

            return {
                "status": active_state,
                "enabled": unit_file_state == "enabled",
            }
        except Exception:
            # Unit might not be loaded, try LoadUnit
            try:
                unit_path = systemd.LoadUnit(service_name)
                unit = bus.get(".systemd1", unit_path)

                active_state = unit.ActiveState
                unit_file_state = unit.UnitFileState

                return {
                    "status": active_state,
                    "enabled": unit_file_state == "enabled",
                }
            except Exception as e:
                return {"status": "not-found", "enabled": False, "error": str(e)}

    except ImportError:
        # Fallback to subprocess if pydbus is not available
        return get_service_status_fallback(service_name)
    except Exception as e:
        return {"status": "error", "enabled": False, "error": str(e)}


def get_service_status_fallback(service_name: str) -> dict[str, Any]:
    """Fallback: Get service status using subprocess"""
    import subprocess

    try:
        result = subprocess.run(
            ["systemctl", "is-active", service_name],
            capture_output=True,
            text=True,
            timeout=5,
        )
        status = result.stdout.strip()

        enabled_result = subprocess.run(
            ["systemctl", "is-enabled", service_name],
            capture_output=True,
            text=True,
            timeout=5,
        )
        enabled = enabled_result.stdout.strip() == "enabled"

        return {"status": status, "enabled": enabled}
    except subprocess.TimeoutExpired:
        return {"status": "unknown", "enabled": False}
    except Exception as e:
        return {"status": "error", "enabled": False, "error": str(e)}


def control_service_via_dbus(
    service_name: str, action: ServiceAction
) -> dict[str, Any]:
    """Control a systemd service using D-Bus"""
    try:
        from pydbus import SystemBus

        bus = SystemBus()
        systemd = bus.get(".systemd1")

        # Map actions to systemd manager methods
        if action == ServiceAction.start:
            systemd.StartUnit(service_name, "replace")
        elif action == ServiceAction.stop:
            systemd.StopUnit(service_name, "replace")
        elif action == ServiceAction.restart:
            systemd.RestartUnit(service_name, "replace")

        # Log the action to the journal
        journal.send(
            f"systemd-control-api: {action.value} {service_name}",
            PRIORITY=journal.LOG_INFO,
            SYSLOG_IDENTIFIER="systemd-control-api",
        )

        return {"success": True, "message": f"Service {action.value} successful"}

    except ImportError:
        # Fallback to subprocess if pydbus is not available
        return control_service_fallback(service_name, action)
    except Exception as e:
        journal.send(
            f"systemd-control-api: Failed to {action.value} {service_name}: {e}",
            PRIORITY=journal.LOG_ERR,
            SYSLOG_IDENTIFIER="systemd-control-api",
        )
        return {"success": False, "message": str(e)}


def control_service_fallback(
    service_name: str, action: ServiceAction
) -> dict[str, Any]:
    """Fallback: Control service using subprocess"""
    import subprocess

    try:
        result = subprocess.run(
            ["systemctl", action.value, service_name],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode == 0:
            return {"success": True, "message": f"Service {action.value} successful"}
        else:
            return {
                "success": False,
                "message": f"Service {action.value} failed: {result.stderr}",
            }
    except subprocess.TimeoutExpired:
        return {"success": False, "message": "Command timed out"}
    except Exception as e:
        return {"success": False, "message": str(e)}


# =============================================================================
# FastAPI Application
# =============================================================================

# Global config (loaded at startup)
CONFIG: Config | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown logging"""
    if CONFIG is None:
        raise RuntimeError("CONFIG not initialized. Call init_config() first.")

    # Build security mode description
    security_modes = []
    if CONFIG.has_api_key:
        security_modes.append("API key")
    if CONFIG.has_host_restriction:
        security_modes.append(f"host allowlist ({len(CONFIG.allowed_hosts)} hosts)")

    journal.send(
        f"systemd-control-api: Starting on port {CONFIG.port}, "
        f"monitoring {len(CONFIG.services)} services, "
        f"security: {' + '.join(security_modes)}",
        PRIORITY=journal.LOG_INFO,
        SYSLOG_IDENTIFIER="systemd-control-api",
    )

    print(f"Starting Systemd Control API on port {CONFIG.port}")
    if security_modes:
        print(f"Security: {' + '.join(security_modes)}")
    else:
        print("Security: NONE (reverse proxy mode)")
    if CONFIG.has_host_restriction:
        print(f"Allowed hosts: {', '.join(CONFIG.allowed_hosts)}")
    print(f"Monitoring {len(CONFIG.services)} services:")
    for service in CONFIG.services:
        print(f"  - {service['displayName']} ({service['service']})")

    yield

    journal.send(
        "systemd-control-api: Shutting down",
        PRIORITY=journal.LOG_INFO,
        SYSLOG_IDENTIFIER="systemd-control-api",
    )


def init_config() -> Config:
    """Initialize global config from environment variables."""
    global CONFIG
    CONFIG = get_config()
    return CONFIG


def get_cors_origins() -> list[str]:
    """Get CORS origins based on allowed hosts configuration.

    If allowed_hosts is configured, converts them to origin URLs.
    If no security is configured, allows all origins (for reverse proxy mode).
    Otherwise returns empty list (restrictive CORS).
    """
    if CONFIG is None:
        return []

    # If no security is configured at all, allow all origins
    # (reverse proxy deployment where proxy handles security)
    if not CONFIG.has_api_key and not CONFIG.has_host_restriction:
        return ["*"]

    # If host restriction is configured, convert to CORS origins
    if not CONFIG.has_host_restriction:
        return []

    origins = []
    for host in CONFIG.allowed_hosts:
        # Handle localhost specially
        if host.lower() == "localhost":
            origins.extend(["http://localhost", "https://localhost"])
        elif "/" not in host:  # Not CIDR, exact IP or hostname
            origins.extend([f"http://{host}", f"https://{host}"])
        # CIDR ranges can't be used directly in CORS,
        # IP check is done in verify_security

    return origins


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    application = FastAPI(
        title="Systemd Control API",
        description="HTTP API for monitoring and controlling systemd services",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Configure CORS middleware
    # Must be done at app creation, not during lifespan
    cors_origins = get_cors_origins()
    application.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=bool(cors_origins),
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    return application


# Initialize config at module load time (for uvicorn import)
# This may fail if env vars aren't set, which is expected during testing
try:
    init_config()
except ValueError:
    # Config will be initialized later in main() or tests
    pass

# Create the app instance
app = create_app()

# Security
security = HTTPBearer(auto_error=False)


def is_ip_allowed(client_ip: str, allowed_hosts: list[str]) -> bool:
    """Check if client IP is in the allowed hosts list.

    Supports:
    - Exact IP match (e.g., "192.168.1.100")
    - CIDR notation (e.g., "192.168.1.0/24")
    - Localhost variations ("localhost", "127.0.0.1", "::1")
    """
    # Normalize localhost
    localhost_aliases = {"localhost", "127.0.0.1", "::1"}

    try:
        client_addr = ip_address(client_ip)
    except ValueError:
        # Not a valid IP, do string comparison
        return client_ip in allowed_hosts

    for allowed in allowed_hosts:
        # Handle localhost specially
        if allowed.lower() == "localhost":
            if client_ip in localhost_aliases or str(client_addr) in localhost_aliases:
                return True
            continue

        try:
            # Try CIDR notation first
            if "/" in allowed:
                if client_addr in ip_network(allowed, strict=False):
                    return True
            else:
                # Exact IP match
                if client_addr == ip_address(allowed):
                    return True
        except ValueError:
            # Not a valid IP/network, do string comparison
            if client_ip == allowed:
                return True

    return False


async def verify_security(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> None:
    """Verify request security based on configured methods.

    Security logic:
    - If no security is configured: allow all requests (for reverse proxy usage)
    - If both API key and host restriction are configured: both must pass
    - If only API key is configured: API key must be valid
    - If only host restriction is configured: client IP must be allowed
    """
    if CONFIG is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server not configured",
        )

    client_host = request.client.host if request.client else "unknown"

    # If no security is configured, allow all requests
    if not CONFIG.has_api_key and not CONFIG.has_host_restriction:
        journal.send(
            f"systemd-control-api: Access granted from {client_host} (no security configured)",
            PRIORITY=journal.LOG_DEBUG,
            SYSLOG_IDENTIFIER="systemd-control-api",
        )
        return

    api_key_valid = False
    host_valid = False

    # Check API key if configured
    if CONFIG.has_api_key:
        if credentials and credentials.credentials == CONFIG.api_key:
            api_key_valid = True

    # Check host if configured
    if CONFIG.has_host_restriction:
        if request.client and is_ip_allowed(request.client.host, CONFIG.allowed_hosts):
            host_valid = True

    # Determine if access should be granted
    access_granted = False

    if CONFIG.has_api_key and CONFIG.has_host_restriction:
        # Both configured: both must pass
        access_granted = api_key_valid and host_valid
    elif CONFIG.has_api_key:
        # Only API key configured
        access_granted = api_key_valid
    elif CONFIG.has_host_restriction:
        # Only host restriction configured
        access_granted = host_valid

    if not access_granted:
        # Build detailed error message
        reasons = []
        if CONFIG.has_api_key and not api_key_valid:
            reasons.append("invalid or missing API key")
        if CONFIG.has_host_restriction and not host_valid:
            reasons.append(f"host {client_host} not in allowed list")

        journal.send(
            f"systemd-control-api: Access denied from {client_host}: {', '.join(reasons)}",
            PRIORITY=journal.LOG_WARNING,
            SYSLOG_IDENTIFIER="systemd-control-api",
        )

        # Use 401 for auth issues, 403 for host-only issues
        if CONFIG.has_api_key and not api_key_valid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Access denied: {', '.join(reasons)}",
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: {', '.join(reasons)}",
            )


def get_service_by_name(service_name: str) -> dict | None:
    """Find a service in the configured services list"""
    if CONFIG is None:
        return None
    return next(
        (s for s in CONFIG.services if s["service"] == service_name),
        None,
    )


# =============================================================================
# API Endpoints
# =============================================================================


@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """Health check endpoint (no authentication required)"""
    return HealthResponse(
        status="healthy",
        timestamp=datetime.now().isoformat(),
        services_count=len(CONFIG.services) if CONFIG else 0,
    )


@app.get(
    "/services",
    response_model=ServicesResponse,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    tags=["Services"],
)
async def get_services(_: None = Depends(verify_security)):
    """Get status of all configured services"""
    if CONFIG is None:
        raise HTTPException(status_code=500, detail="Server not configured")

    services_status = []

    for service_info in CONFIG.services:
        service_name = service_info["service"]
        status_info = get_service_status_via_dbus(service_name)

        service_data = ServiceStatus(
            service=service_name,
            display_name=service_info["displayName"],
            description=service_info["description"],
            status=status_info["status"],
            enabled=status_info["enabled"],
            metadata=service_info.get("metadata"),
        )
        services_status.append(service_data)

    return ServicesResponse(
        last_updated=datetime.now().isoformat(),
        services=services_status,
    )


@app.post(
    "/service/{service_name}/{action}",
    response_model=ServiceControlResponse,
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
    tags=["Services"],
)
async def control_service(
    service_name: str,
    action: ServiceAction,
    _: None = Depends(verify_security),
):
    """Control a service (start, stop, restart)"""
    service_info = get_service_by_name(service_name)

    if not service_info:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Service '{service_name}' not found in configured services",
        )

    result = control_service_via_dbus(service_name, action)

    return ServiceControlResponse(
        success=result["success"],
        message=result["message"],
        display_name=service_info["displayName"],
    )


# =============================================================================
# Main Entry Point
# =============================================================================


def main():
    """Start the API server with uvicorn"""
    # Ensure config is loaded
    global CONFIG
    if CONFIG is None:
        CONFIG = get_config()

    uvicorn.run(
        "systemd_control_api:app",
        host="0.0.0.0",
        port=CONFIG.port,
        log_level="info",
        access_log=True,
    )


if __name__ == "__main__":
    main()
