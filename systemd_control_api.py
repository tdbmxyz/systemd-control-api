#!/usr/bin/env python3
"""
Systemd Control API Server
Provides HTTP API endpoints for monitoring and controlling systemd services
"""

import json
import os
from contextlib import asynccontextmanager
from datetime import datetime
from enum import Enum
from typing import Any

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from systemd import journal


# =============================================================================
# Configuration
# =============================================================================


def get_config() -> tuple[str, int, list[dict]]:
    """Get configuration from environment variables"""
    api_key = os.environ.get("SYSTEMD_CONTROL_API_KEY")
    if not api_key:
        raise ValueError("SYSTEMD_CONTROL_API_KEY environment variable is required")

    port = int(os.environ.get("SYSTEMD_CONTROL_API_PORT", "8080"))

    services_json = os.environ.get("SYSTEMD_CONTROL_API_SERVICES", "[]")
    try:
        services = json.loads(services_json)
    except json.JSONDecodeError:
        raise ValueError("SYSTEMD_CONTROL_API_SERVICES must be valid JSON")

    return api_key, port, services


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
API_KEY: str = ""
PORT: int = 8080
SERVICES: list[dict] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: load config on startup"""
    global API_KEY, PORT, SERVICES
    API_KEY, PORT, SERVICES = get_config()

    journal.send(
        f"systemd-control-api: Starting on port {PORT}, monitoring {len(SERVICES)} services",
        PRIORITY=journal.LOG_INFO,
        SYSLOG_IDENTIFIER="systemd-control-api",
    )

    print(f"Starting Systemd Control API on port {PORT}")
    print(f"Monitoring {len(SERVICES)} services:")
    for service in SERVICES:
        print(f"  - {service['displayName']} ({service['service']})")

    yield

    journal.send(
        "systemd-control-api: Shutting down",
        PRIORITY=journal.LOG_INFO,
        SYSLOG_IDENTIFIER="systemd-control-api",
    )


app = FastAPI(
    title="Systemd Control API",
    description="HTTP API for monitoring and controlling systemd services",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security
security = HTTPBearer()


async def verify_api_key(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> str:
    """Verify the API key from the Authorization header"""
    if credentials.credentials != API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
    return credentials.credentials


def get_service_by_name(service_name: str) -> dict | None:
    """Find a service in the configured services list"""
    return next(
        (s for s in SERVICES if s["service"] == service_name),
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
        services_count=len(SERVICES),
    )


@app.get(
    "/services",
    response_model=ServicesResponse,
    responses={401: {"model": ErrorResponse}},
    tags=["Services"],
)
async def get_services(_: str = Depends(verify_api_key)):
    """Get status of all configured services"""
    services_status = []

    for service_info in SERVICES:
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
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
    tags=["Services"],
)
async def control_service(
    service_name: str,
    action: ServiceAction,
    _: str = Depends(verify_api_key),
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
    # Load config early to get port and validate
    global API_KEY, PORT, SERVICES
    API_KEY, PORT, SERVICES = get_config()

    uvicorn.run(
        "systemd_control_api:app",
        host="0.0.0.0",
        port=PORT,
        log_level="info",
        access_log=True,
    )


if __name__ == "__main__":
    main()
