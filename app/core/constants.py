"""Application constants."""


class StatusCode:
    """HTTP Status codes used throughout the API."""

    OK = 200
    CREATED = 201
    ACCEPTED = 202
    NO_CONTENT = 204
    BAD_REQUEST = 400
    UNAUTHORIZED = 401
    FORBIDDEN = 403
    NOT_FOUND = 404
    CONFLICT = 409
    UNPROCESSABLE = 422
    INTERNAL_ERROR = 500
    SERVICE_UNAVAILABLE = 503


# API versioning
API_PREFIX = "/api"

# Default values
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

# Process states
class ProcessState:
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"
    PENDING = "pending"
    RESTARTING = "restarting"


# Service statuses
class ServiceStatus:
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


# Backend types
class BackendType:
    CLAUDE_CODE = "claude-code"
    HERMES_NATIVE = "hermes-native"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


# Session statuses
class SessionStatus:
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PENDING = "pending"
