import secrets
import threading
import time
from functools import cached_property

import httpx
import uvicorn
from aiohttp.abc import HTTPException
from fastapi import FastAPI, Request
from loguru import logger as log
from starlette.responses import RedirectResponse, JSONResponse
from thread_manager import ManagedThread
from toomanyports import PortManager

import fast_auth


# noinspection PyUnusedLocal
class FastAuth(FastAPI):
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
            from fast_auth import auth_server
            while not auth_server.thread.is_alive():
                time.sleep(1)
            auth_server.return_url = request.url

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
                    response = await client.post(f"{fast_auth.URL}/api/exchange", json={"session_token": session})

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
                        redirect_response = RedirectResponse(f"{fast_auth.URL}/?return_url={return_url}")
                        redirect_response.set_cookie("session", session, max_age=3600 * 8)
                        return redirect_response

                    if not response.status_code == 200 or 302:
                        return JSONResponse("i messed up lol ")

                except Exception as e:
                    return JSONResponse("i messed up lol ")
            #
            # log.warning("[FastAuth]: Continuing without user...")
            # response_obj = await call_next(request)
            # if not request.cookies.get("session"):
            #     response_obj.set_cookie("session", session, max_age=3600 * 8)
            # return response_obj

    @cached_property
    def uvicorn_cfg(self) -> uvicorn.Config:
        return uvicorn.Config(
            app=self,
            host=self.host,
            port=self.port,
            # reload=True,
            # log_config=,
        )

    @cached_property
    def thread(self) -> threading.Thread:  # type: ignore
        def proc(self):
            if self.verbose: log.info(f"[{self}]: Launching microservice on {self.host}:{self.port}")
            server = uvicorn.Server(config=self.uvicorn_cfg)
            server.run()

        return ManagedThread(proc, self)
