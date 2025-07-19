import ast
import asyncio
import inspect
import time
from dataclasses import dataclass
from functools import cached_property
from types import SimpleNamespace
from typing import Any

import aiohttp
from loguru import logger as log
from singleton_decorator import singleton

from toomanythreads import ThreadedServer

import asyncio
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from loguru import logger as log

from fast_template import FastTemplates

@dataclass
class PageConfig:
    name: str
    title: str
    type: str
    cwd: Path
    color: Optional[str] = None  # hex color for styling
    icon: Optional[str] = None  # icon class or emoji
    auto_discovered: bool = False  # flag for auto-discovered pages

def extract_title_from_html(html_file: Path) -> Optional[str]:
    """Extract title from HTML file's <title> tag"""
    try:
        content = html_file.read_text(encoding='utf-8')
        import re
        title_match = re.search(r'<title[^>]*>(.*?)</title>', content, re.IGNORECASE | re.DOTALL)
        if title_match:
            title = title_match.group(1).strip()
            log.debug(f"Extracted title '{title}' from {html_file.name}")
            return title
    except Exception as e:
        log.debug(f"Could not extract title from {html_file.name}: {e}")
    return None

def generate_color_from_name(name: str) -> str:
    """Generate a consistent color hex code based on the page name"""
    hash_value = hash(name)
    hue = abs(hash_value) % 360
    saturation = 70
    lightness = 50

    import colorsys
    r, g, b = colorsys.hls_to_rgb(hue / 360, lightness / 100, saturation / 100)
    return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"

@singleton
class PublicApp(ThreadedServer):
    @cached_property
    def cwd(self) -> SimpleNamespace:
        ns = SimpleNamespace(
            path=Path.cwd(),
            index=Path.cwd() / "index",
            index_file=Path.cwd() / "index" / "index.html",
            static_pages=Path.cwd() / "static_pages"
        )
        for name, p in vars(ns).items():
            if p.suffix:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.touch(exist_ok=True)
                if self.verbose:
                    log.debug(f"[{self}]: Ensured file {p}")
            else:
                p.mkdir(parents=True, exist_ok=True)
                if self.verbose:
                    log.debug(f"[{self}]: Ensured directory {p}")
        return ns

    @cached_property
    def base_url(self) -> str:
        url = f"http://{self.host}:{self.port}"
        if self.verbose: log.debug(f"[{self}]: base_url set to {url}")
        return url

    @cached_property
    def api(self) -> 'Macroservice':
        if self.verbose: log.debug(f"[{self}]: Initializing Macroservice API")
        return Macroservice()

    @cached_property
    def pages(self) -> List[PageConfig]:
        if self.verbose: log.debug(f"[{self}]: Discovering pages in {self.cwd.static_pages}")
        discovered: List[PageConfig] = []
        for page_path in self.cwd.static_pages.glob("*.html"):
            title = extract_title_from_html(page_path) or page_path.stem.replace('_', ' ').title()
            cfg = PageConfig(
                name=page_path.name,
                title=title,
                type="static",
                cwd=self.cwd.static_pages,
                color=generate_color_from_name(page_path.name),
                icon="📄",
                auto_discovered=True
            )
            discovered.append(cfg)
            if self.verbose: log.debug(f"[{self}]: Discovered page {cfg.name} titled '{cfg.title}'")
        return discovered

    @cached_property
    def index(self) -> FastTemplates:
        if self.verbose: log.debug(f"[{self}]: Initializing FastTemplates at {self.cwd.index}")
        return FastTemplates(self.cwd.index)

    @cached_property
    def static_env(self):
        return FastTemplates(self.cwd.static_pages)

    def __init__(self, host="localhost", port=None, verbose=True):
        super().__init__(host=host, port=port, verbose=verbose)
        app = self
        _ = self.pages

        @self.get("/", response_class=HTMLResponse)
        async def home(request: Request):
            if self.verbose:
                log.debug(f"[{self}]: GET / home endpoint")
            return self.index.TemplateResponse(
                f"{self.cwd.index_file.name}",
                {"request": request, "pages": self.pages}
            )

        @self.get("/page/{page_name}")
        async def get_page(page_name: str, request: Request) -> HTMLResponse:
            """Serve a specific static page by filename."""
            if self.verbose:
                log.debug(f"[{self}]: Received GET /page/{page_name}")
            page = next((p for p in self.pages if p.name == page_name), None)
            if not page:
                if self.verbose:
                    log.warning(f"[{self}]: Page not found: {page_name}")
                raise HTTPException(status_code=404, detail="Page not found")

            if page.type == "static":
                template_name = page.name
                template_path = self.cwd.static_pages / template_name
                if self.verbose:
                    log.debug(f"[{self}]: Serving static template {template_name} from {template_path}")
                if not template_path.exists():
                    if self.verbose:
                        log.error(f"[{self}]: Template file missing: {template_path}")
                    raise HTTPException(status_code=404, detail=f"Template {template_name} not found")
                return self.static_env.TemplateResponse(
                    template_name,
                    {"request": request, "page": page}
                )

        self.thread.start()

@singleton
class Macroservice:
    microservices = {}

    def __getattr__(self, name: str):
        if name in self.microservices:
            return self.microservices[name].api
        raise AttributeError(f"'{type(self).__name__}' has no microserice named '{name}'")

    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith('_') or name in ['__annotations__']:
            super().__setattr__(name, value)
        else: self[name]: Microservice

Macroservice = Macroservice()
Mac = Macroservice
Macro = Macroservice
Macroserv = Macroservice

class Microservice(ThreadedServer):
    _last_route_count = None
    _api_client = None

    def __init__(self, host="localhost", port=None, alias: str = None, verbose=True):
        super().__init__(host=host, port=port, verbose=verbose)
        _ = self.base_url
        self.name = str(port)
        if alias: self.name = alias
        Macroservice.microservices[self.name] = self

    def __repr__(self):
        return f"[Microservices.{self.name}]"

    @cached_property
    def base_url(self):
        return f"http://{self.host}:{self.port}"

    @property
    def api(self):
        """Smart API client - only regenerates when routes change"""
        current_route_count = len(self.routes)

        if (self._api_client is None or
            current_route_count != self._last_route_count):

            if self.verbose: log.debug(f"Regenerating API client ({self._last_route_count} -> {current_route_count} routes)")

            self._api_client = APIClient(self)
            self._last_route_count = current_route_count

        return self._api_client

Microserv = Microservice
Micro = Microservice
Mic = Microservice

@dataclass
class Response:
    status: int
    method: str
    headers: dict
    body: Any

class APIClient:
    def __init__(self, app: Microservice):
        self.app = app

        for route in app.routes:
            if hasattr(route, 'endpoint') and hasattr(route.endpoint, '__name__'):
                method_name = route.endpoint.__name__  # Use function name!
                setattr(self, method_name, self._make_method(route))

    def _make_method(self, route):
        """Create a simple async method for each route"""
        async def api_call(*args, **kwargs):
            if not self.app.thread.is_alive(): raise RuntimeError(f"{self.app.base_url} isn't running!")
            method = list(route.methods)[0] if route.methods else 'GET'
            path = route.path

            # Simple path parameter substitution
            for i, arg in enumerate(args):
                path = path.replace(f'{{{list(route.path_regex.groupindex.keys())[i]}}}', str(arg), 1)

            async with aiohttp.ClientSession() as session:
                async with session.request(method, f"{self.app.base_url}{path}", **kwargs) as res:
                    try:
                        content_type = res.headers.get("Content-Type", "")
                        if "json" in content_type:
                            content = await res.json()
                        else:
                            content = await res.text()
                    except Exception as e:
                        content = await res.text()  # always fallback
                        log.warning(f"{self}: Bad response decode → {e} | Fallback body: {content}")

                    resp = Response(
                        status=res.status,
                        method=method,
                        headers=dict(res.headers),
                        body=content,
                    )
                    if self.app.verbose: log.debug(f"{self.app}:\n  - req={res.url} - args={args}\n  - kwargs={kwargs}\n  - resp={resp}")
                    return resp

        return api_call

async def debug():
    server = Microservice(alias="foobar")
    server.cache = {}
    server.thread.start()

    @server.get("/users/{user_id}")
    async def get_user(user_id: str):
        return {"user_id": user_id, "name": "John"}

    @server.post("/cache/{key}")
    async def set_cache(key: str, value: str):
        server.cache[key] = value
        return {"status": "stored"}

    @server.get("/cache/{key}")
    async def get_cache(key: str):
        return {"value": server.cache.get(key, "not found")}

    # Test initial API methods (using function names)
    user_data = await server.api.get_user("123")
    cache_value = await server.api.get_cache("mykey")
    set_result = await server.api.set_cache("mykey", json={"value": "myvalue"})
    # Verify cache was set
    updated_cache = await server.api.get_cache("mykey")

    # Add new route
    @server.get("/health")
    async def health_check():
        return {"status": "healthy", "cache_size": len(server.cache)}

    @server.post("/reset")
    async def reset_cache():
        server.cache.clear()
        return {"status": "cache cleared"}

    # Test new methods
    health = await server.api.health_check()
    reset = await server.api.reset_cache()
    # Verify cache was cleared
    final_cache = await server.api.get_cache("mykey")
    Mac
    Macro
    Macroserv
    Macroservice
    reset = await Mac.foobar.reset_cache()

    time.sleep(100)

if __name__ == "__main__":
    # asyncio.run(debug())
    PublicApp().thread.start()
    time.sleep(100)