"""Canonical request-path projection shared by routing security middleware."""

from starlette._utils import get_route_path
from starlette.requests import Request


def get_request_route_path(request: Request) -> str:
    """Return the same root-path-adjusted value Starlette routes match."""
    return get_route_path(request.scope)
