import asyncio
import time
from pathlib import Path
from typing import Any

import requests
from fastapi import FastAPI
from loguru import logger as log
from toomanyports import PortManager
from toomanythreads import ThreadedServer

from microservices.core import PublicApp
from pycloudflare import Cloudflare


class Gateway(Cloudflare):
    def __init__(
            self,
            host: str = None,
            port: int = None,
            cfg: Path = None,
            app: Any = None,
            verbose: bool = True,
    ) -> None:
        self.host = "localhost" if host is None else host
        self.port = PortManager.random_port() if port is None else port
        if cfg: Cloudflare.__init__(self, toml=cfg)
        else: Cloudflare.__init__(self)
        self.cloudflare_cfg.service_url = self.url

        if app: self.app = app
        else: self.app = PublicApp()

        self.verbose = verbose
        if self.verbose: log.success(f"[{self}]: Initialized successfully!\n  - host={self.host}\n  - port={self.port}")

        @self.get("/")
        async def index(path):
            url = app.url
            log.debug(f"{self}: Retrieving {url} from {self.app}")
            requests.get(url)
            log.debug(url)
            return None

    async def launch(self):
        loc = self.thread
        glo = await self.cloudflare_thread
        loc.start()
        glo.start()

async def debug():
    g = Gateway()
    await g.launch()

if __name__ == "__main__":
    asyncio.run(debug())
    time.sleep(1000)
