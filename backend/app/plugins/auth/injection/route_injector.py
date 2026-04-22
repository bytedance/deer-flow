"""Inject config-driven auth guards into FastAPI routes."""

from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.dependencies.utils import get_dependant, get_flat_dependant, get_parameterless_sub_dependant
from fastapi.routing import APIRoute, _should_embed_body_fields, get_body_field, request_response

from app.plugins.auth.injection.route_guard import enforce_route_policy


def _rebuild_route(route: APIRoute) -> None:
    route.dependant = get_dependant(path=route.path_format, call=route.endpoint, scope="function")
    for depends in route.dependencies[::-1]:
        route.dependant.dependencies.insert(
            0,
            get_parameterless_sub_dependant(depends=depends, path=route.path_format),
        )
    route._flat_dependant = get_flat_dependant(route.dependant)
    route._embed_body_fields = _should_embed_body_fields(route._flat_dependant.body_params)
    route.body_field = get_body_field(
        flat_dependant=route._flat_dependant,
        name=route.unique_id,
        embed_body_fields=route._embed_body_fields,
    )
    route.app = request_response(route.get_route_handler())


def install_route_guards(app: FastAPI) -> None:
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if any(getattr(dependency, "dependency", None) is enforce_route_policy for dependency in route.dependencies):
            continue
        route.dependencies.append(Depends(enforce_route_policy))
        _rebuild_route(route)


__all__ = ["install_route_guards"]
