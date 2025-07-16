from functools import cached_property

import uvicorn
from fastapi import FastAPI

from loguru import logger as log
from thread_manager import ManagedThread
from toomanyports import PortManager


class Gateway(FastAPI):
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