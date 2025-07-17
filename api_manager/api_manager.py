import time
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Optional

import aiohttp
import toml
from fastapi import FastAPI
from loguru import logger as log

from fast_auth import FastAuth


@dataclass
class Headers:
    """
    Container for HTTP index used in outgoing API requests.

    Automatically ensures the presence of an 'Accept' header (defaults to 'application/json').
    Useful for injecting standard index like Authorization, User-Agent, etc.

    Example:
        Headers(index={
            "Authorization": "Bearer abc123",
            "User-Agent": "my-client"
        })
    """
    index: Dict[str, str]
    """
    A dictionary of HTTP index to include in the request.
    Must have string keys and values. Will be validated and normalized.
    """
    accept: Optional[str] = None
    """
    Optional override for the Accept header.
    If not provided, defaults to 'application/json'.
    Injected into the index dict automatically during post-init.
    """

    def __post_init__(self):
        self.accept = self.accept or "application/json"
        self.index["Accept"] = self.accept
        for k, v in self.index.items():
            setattr(self, k.lower().replace("-", "_"), v)
        if not self._validate(): log.error("[Headers] Validation failed")

    def _validate(self) -> bool:
        try:
            if not isinstance(self.index, dict): raise TypeError
            for k, v in self.index.items():
                if not isinstance(k, str) or not isinstance(v, str): raise ValueError
            # if hasattr(self, "authorization") and not self.authorization.startswith("Bearer "):
            #    raise ValueError("Authorization must start with Bearer")
        except Exception as e:
            log.error(f"[Headers] Invalid index: {e}")
            return False
        return True

    @cached_property
    def as_dict(self):
        return self.index

@dataclass
class Routes:
    """
    Defines a base URL and a mapping of route keys to endpoint paths.

    Used to centralize route definitions and build full request URLs.
    Allows access via dictionary-like syntax: urls["status"] → full path.

    Example:
        Routes(
            base="https://api.example.com",
            api_routes={"status": "/v1/status", "info": "/v1/info"}
        )
    """
    base: str
    """
    The base URL for all api_routes (e.g., "https://api.example.com").
    Should not end with a trailing slash.
    """
    routes: Dict[str, str]
    """
    Dictionary mapping route names to URL suffixes (e.g., {"status": "/v1/status"}).
    Each value is appended to the base URL during resolution.
    """

    def __post_init__(self):
        if not self._validate(): log.error("[Routes] Validation failed")

    def _validate(self) -> bool:
        try:
            if not isinstance(self.base, str) or not isinstance(self.routes, dict): raise TypeError
            for k, v in self.routes.items():
                if not isinstance(k, str) or not isinstance(v, str): raise ValueError
        except Exception as e:
            log.error(f"[Routes] Invalid api_routes: {e}")
            return False
        return True

    def __getitem__(self, key: str) -> str:
        """
        Resolve a named route into a full URL.

        Retrieves the full URL for a given route key by appending the mapped path
        to the base URL defined in the instance.

        Example:
            urls["status"] -> "https://api.example.com/status/200"

        :param key: The name of the route (must exist in self.api_routes)
        :return: A full URL string composed of base + route path
        :raises KeyError: If the provided key does not exist in the route map
        """
        if key not in self.routes: raise KeyError(f"Missing route: {key}")
        return self.base + self.routes[key]

# noinspection PyUnusedLocal
class API:
    api_headers: Headers
    """
    A Headers instance containing all request index for the API.
    """
    api_routes: Routes
    """
    A Routes instance defining the base URL and route mappings.
    """
    api_vars: dict | None = None
    """
    Additional api_vars specified in config...
    """
    def __init__(self, path: Path):
        data = None
        with open(path, "r", encoding="utf-8") as f:
            data = toml.load(f)
        if data is None: raise ValueError

        def replace_vars(d: dict, _vars: dict):
            for k, v in d.items():
                if isinstance(v, str):
                    for var_key, var_val in _vars.items():
                        d[k] = d[k].replace(f"${var_key.upper()}", var_val)
                elif isinstance(v, dict):
                    replace_vars(v, _vars)

        replace_vars(data["headers"], data["vars"])
        replace_vars(data["url"], data["vars"])
        replace_vars(data["url"]["routes"], data["vars"])

        self.api_headers = Headers(data["headers"])
        self.api_routes = Routes(
                base=data["url"]["base"],
                routes=data["url"]["routes"]
            )
        self.api_vars = data["vars"]

a = API(Path(Path.cwd().parent / "test.toml"))
log.debug(a.api_headers)
log.debug(a.api_routes)

@dataclass
class Response:
    status: int
    method: str
    headers: dict
    body: Any

class Receptionist(API):
    cache: dict[str | SimpleNamespace] = {}

    def __init__(self, path):
        API.__init__(self, path=path)

    async def api_request(self,
                      method: str,
                      route: str,
                      append: str = "",
                      format: dict = None,
                      force_refresh: bool = False, **kw) -> Response:
        try:
            path = self.api_routes[route]
        except KeyError:
            path = route

        if format:
            path = path.format(**format)
        if append:
            path += append

        headers = self.api_headers.as_dict

        if not force_refresh:
            if path in self.cache: return self.cache[path]

        log.debug(f"{self}: Attempting request to API:\n  - method={method}\n  - path={path}")

        async with aiohttp.ClientSession(headers=headers) as ses:
            async with ses.request(method.upper(), path, **kw) as res:
                try:
                    content_type = res.headers.get("Content-Type", "")
                    if "json" in content_type:
                        content = await res.json()
                    else:
                        content = await res.text()
                except Exception as e:
                    content = await res.text()  # always fallback
                    log.warning(f"{self}: Bad response decode → {e} | Fallback body: {content}")

                out = Response(
                    status=res.status,
                    method=method,
                    headers=dict(res.headers),
                    body=content,
                )

                self.cache[path] = out
                return self.cache[path]

    async def api_get(self, route, append=None, format=None, force_refresh=False, **kw):
        return await self.api_request("get", route, append=append, format=format, force_refresh=force_refresh, **kw)

    async def api_post(self, route, append=None, format=None, force_refresh=False, **kw):
        return await self.api_request("post", route, append=append, format=format, force_refresh=force_refresh, **kw)

    async def api_put(self, route, append=None, format=None, force_refresh=False, **kw):
        return await self.api_request("put", route, append=append, format=format, force_refresh=force_refresh, **kw)

    async def api_delete(self, route, append=None, format=None, force_refresh=False, **kw):
        return await self.api_request("delete", route, append=append, format=format, force_refresh=force_refresh, **kw)

class APIGateway(Receptionist, FastAuth):

    def __init__(self, path: Path):
        Receptionist.__init__(self, path)
        FastAuth.__init__(self)

        @self.get("/")
        async def _index():
            return self.api_routes.routes

        @self.get("/cache")
        async def _cache():
            return self.cache

        @self.get("/cache/{key}")
        async def _cache_key(key):
            return self.cache[key]

        @self.get("/api/{method}/{api_route}/")
        async def _request_from_api(method, api_route):
            if method is None or "null": method = "get"
            valid_methods = ["get", "post", "put", "delete"]
            if method not in valid_methods: raise ValueError(f"{method} is not included within {valid_methods}")
            if api_route not in self.api_routes.routes: raise ValueError(f"{api_route} is not in {self.api_routes}")

            return await self.api_request(method, api_route)

# b = APIGateway(Path(Path.cwd().parent / "test.toml"))
# b.thread.start()
# time.sleep(9000)