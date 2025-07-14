import re
import inspect
import re
import secrets
import threading
import time
import tomllib as toml
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from threading import Thread
from types import SimpleNamespace
from typing import Any
from typing import Dict
from typing import Type

import httpx
from fastapi import FastAPI
import uvicorn
from functools import cached_property
from loguru import logger as log
from typing import Optional

from starlette.templating import Jinja2Templates
from toomanyports import PortManager

import loguru
import uvicorn
from fastapi import FastAPI
from loguru import logger as log
from pydantic import BaseModel
# from pywershell import PywershellLive
from singleton_decorator import singleton

from thread_manager import ManagedThread
from fastapi import FastAPI, Request
import fast_auth


# @dataclass
# class MicroserviceSchema:
#     host: str
#     port: int
#     url: str = None
#
#     def __post_init__(self):
#         if self.url is None:
#             self.url = f"http://{self.host}:{self.port}"
#
# class ConfigSchema(BaseModel):
#     microservices: list[MicroserviceSchema]
#
#     @classmethod
#     def from_dict(cls, schema):
#         microservices = []
#         for key in schema:
#             val = schema[key]
#             ms = MicroserviceSchema(**val)
#             microservices.append(ms)
#
#         return ConfigSchema(
#             microservices=microservices
#         )
#
# #for documentation purposes
# example_schema = {
#     "microservice": {
#         "host": "localhost",
#         "port": "1234"
#     }
# }
#
# load_cfg = ConfigSchema.from_dict

@singleton
class MicroserviceManager:
    def __setitem__(self, port, obj) -> 'Microservice':
        self[port] = obj
        return self[port]

    def __getitem__(self, port: int) -> 'Microservice':
        if port not in self.__dict__:
            return self.__getitem__(port)
        return self[port]

MicroserviceManager = MicroserviceManager()

class Microservice(FastAPI):
    def __init__(
        self,
        host: str = None,
        port: int = None,
        reload: bool = False,
        verbose: bool = True,
    ) -> None:
        self.host = "localhost" if host is None else host
        self.port = PortManager.random_port() if port is None else port
        self.verbose = verbose
        super().__init__(debug=self.verbose)
        if self.verbose: log.success(f"[{self}]: Initialized successfully!\n  - host={self.host}\n  - port={self.port}")

        @self.middleware("http")
        async def oauth_middleware(request: Request, call_next):
            # Get or create session
            session = request.cookies.get("session")
            if not session:
                log.debug(f"[FastAuth] Couldn't find a session for {request.headers}")
                session = secrets.token_urlsafe(32)
                log.debug(f"[FastAuth]: Created a cookie!:\nsession={session}")

            # Skip static files
            if request.url.path.startswith("/static"):
                return await call_next(request)

            # Try to get user from OAuth service
            async with httpx.AsyncClient() as client:
                log.debug(f"[FastAuth] Attempting to get a user from OAuth!")
                try:
                    response = await client.post(f"{oauth_url}/api/exchange", json={"session_token": session})

                    if response.status_code == 200:
                        # Got user - set session cookie and continue
                        request.state.user = response.json()
                        response_obj = await call_next(request)
                        if not request.cookies.get("session"):
                            response_obj.set_cookie("session", session, max_age=3600 * 8)
                        return response_obj

                    elif response.status_code == 302:
                        # Need OAuth - redirect with return URL and session
                        return_url = str(request.url)
                        redirect_response = RedirectResponse(f"{oauth_url}/?return_url={return_url}")
                        redirect_response.set_cookie("session", session, max_age=3600 * 8)
                        return redirect_response

                except:
                    pass

            # Continue without user
            log.warning("[FastAuth]: Continuing without user...")
            response_obj = await call_next(request)
            if not request.cookies.get("session"):
                response_obj.set_cookie("session", session, max_age=3600 * 8)
            return response_obj

    @cached_property
    def uvicorn_cfg(self) -> uvicorn.Config:
        return uvicorn.Config(
            app=self,
            host=self.host,
            port=self.port,
            #reload=True,
            #log_config=,
        )

    @cached_property
    def thread(self) -> threading.Thread: #type: ignore
        def proc(self):
            if self.verbose: log.info(f"[{self}]: Launching microservice on {self.host}:{self.port}")
            server = uvicorn.Server(config=self.uvicorn_cfg)
            server.run()
        return ManagedThread(proc, self)

ms = Microservice()
ms.thread.run()