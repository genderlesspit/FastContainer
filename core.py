import asyncio
import httpx
import logging
import json
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict, Any, Union
from pathlib import Path
import mimetypes

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, Response, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from loguru import logger as log

from fast_template import FastTemplates

app = FastAPI()

@dataclass
class PageConfig:
    name: str
    title: str
    type: str  # "static", "spa", "service"
    template: Optional[str] = None  # for static pages
    entry_point: Optional[str] = None  # for SPAs (index.html or main.js)
    service_url: Optional[str] = None  # for service pages
    path: str = "/"  # endpoint path
    color: Optional[str] = None  # hex color for styling
    icon: Optional[str] = None  # icon class or emoji
    auto_discovered: bool = False  # flag for auto-discovered pages
    assets_dir: Optional[str] = None  # for SPAs - where JS/CSS assets are
    config_file: Optional[str] = None  # for SPAs - package.json, config.json etc
    template_dir: Optional[str] = None  # track which directory the template is in

async def discover_pages() -> List[PageConfig]:
    """Discover all types of pages: static HTML, SPAs, and configured services"""
    discovered_pages = []

    # Check multiple directories for different types of content
    directories_to_check = [
        (Path.cwd() / "static", "static"),      # Traditional static HTML
        (Path.cwd() / "apps", "spa"),           # SPAs and complex apps
    ]

    for base_dir, default_type in directories_to_check:
        if not base_dir.exists():
            log.debug(f"Directory {base_dir} does not exist, skipping")
            continue

        log.debug(f"Scanning {base_dir} for {default_type} content")

        # Check for direct HTML files in the directory
        if default_type == "static":
            html_files = list(base_dir.glob("*.html"))
            for html_file in html_files:
                if html_file.name in ['base.html', 'layout.html', 'template.html']:
                    continue

                page_config = await create_static_page_config(html_file, base_dir)
                discovered_pages.append(page_config)

        # Check subdirectories for SPAs or organized static content
        for item in base_dir.iterdir():
            if item.is_dir():
                # Check for HTML files in subdirectory
                html_files = list(item.glob("*.html"))
                if html_files:
                    # Use the first HTML file or index.html if available
                    main_html = next((f for f in html_files if f.name == 'index.html'), html_files[0])
                    page_config = await create_static_page_config(main_html, item)
                    discovered_pages.append(page_config)

    return discovered_pages

async def create_static_page_config(html_file: Path, base_dir: Path) -> PageConfig:
    """Create PageConfig for static HTML files"""
    page_name = html_file.stem
    if html_file.parent != base_dir:
        # Include parent directory in name if it's in a subdirectory
        page_name = f"{html_file.parent.name}_{page_name}"

    title = await extract_title_from_html(html_file)
    if not title:
        title = page_name.replace('_', ' ').replace('-', ' ').title()

    return PageConfig(
        name=page_name,
        title=title,
        type="static",
        template=html_file.name,  # Just the filename, not relative path
        template_dir=str(html_file.parent),  # Store the full directory path
        color=generate_color_from_name(page_name),
        icon="📄",
        auto_discovered=True
    )

async def extract_title_from_html(html_file: Path) -> Optional[str]:
    """Extract title from HTML file's <title> tag"""
    try:
        content = await asyncio.to_thread(html_file.read_text, encoding='utf-8')

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
    r, g, b = colorsys.hls_to_rgb(hue/360, lightness/100, saturation/100)
    return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"

async def get_all_pages() -> List[PageConfig]:
    """Get all pages auto-discovered"""

    all_pages = []
    discovered_pages = await discover_pages()

    for discovered_page in discovered_pages:
        all_pages.append(discovered_page)

    log.debug(f"Total pages: {len([p for p in all_pages if p.auto_discovered])} auto-discovered = {len(all_pages)}")

    return all_pages

# Global pages cache
PAGES: List[PageConfig] = []

@app.on_event("startup")
async def startup_event():
    """Initialize pages on startup"""
    global PAGES
    PAGES = await get_all_pages()
    log.debug(f"Initialized with {len(PAGES)} total pages")

@app.get("/refresh-pages")
async def refresh_pages():
    """Endpoint to refresh the pages list"""
    global PAGES
    old_count = len(PAGES)
    PAGES = await get_all_pages()
    log.debug(f"Refreshed pages list - was {old_count}, now {len(PAGES)} total pages")
    return {
        "message": f"Refreshed {len(PAGES)} pages",
        "pages": [asdict(p) for p in PAGES]
    }

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Main container page that lists all available pages"""
    container_template = None

    # Look for container template in multiple locations
    for template_dir in ["index", "templates", "."]:
        template_path = Path(template_dir) / "container.html"
        if template_path.exists():
            env = await FastTemplates(template_dir)
            container_template = env
            break

    if not container_template: raise RuntimeError(f"{app.__repr__}: No home template found!")

    return container_template.TemplateResponse("container.html", {
        "request": request,
        "pages": PAGES
    })

@app.get("/page/{page_name}")
async def get_page(page_name: str, request: Request):
    """Serve a specific page based on its type"""
    page = next((p for p in PAGES if p.name == page_name), None)
    if not page:
        log.debug(f"Page not found: {page_name}")
        raise HTTPException(status_code=404, detail="Page not found")

    log.debug(f"Serving page: {page_name} (type: {page.type})")

    if page.type == "static":
        template_dir = page.template_dir or "static"
        log.debug(f"Using template dir: {template_dir}, template: {page.template}")

        # Verify the template file exists
        template_path = Path(template_dir) / page.template
        if not template_path.exists():
            log.debug(f"Template file not found: {template_path}")
            raise HTTPException(status_code=404, detail=f"Template file not found: {page.template}")

        # Get the template environment for this directory
        template_env = await FastTemplates(template_dir)

        # Render the template
        return template_env.TemplateResponse(page.template, {
            "request": request,
            "page": page
        })

if __name__ == "__main__":
    import uvicorn

    # Setup directories
    cwd = Path.cwd()
    directories = ["templates", "static", "apps", "pages", "sites", "index"]

    for dir_name in directories:
        (cwd / dir_name).mkdir(exist_ok=True)

    print("Starting enhanced containerizer...")
    print(f"Created directories: {', '.join(directories)}")
    print("Visit /refresh-pages to reload during development")

    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")