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

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Toggle for verbose logging
VERBOSE_LOGGING = True

def log_verbose(message: str, *args, **kwargs):
    """Verbose logging that can be toggled on/off"""
    if VERBOSE_LOGGING:
        logger.info(message, *args, **kwargs)

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

async def detect_spa_type(page_dir: Path) -> Optional[Dict[str, Any]]:
    """Detect if a directory contains a Single Page Application"""
    spa_indicators = {
        'package.json': 'node',
        'index.html': 'vanilla',
        'main.js': 'vanilla',
        'app.js': 'vanilla',
        'dist/index.html': 'built',
        'build/index.html': 'react',
        'public/index.html': 'react-dev',
        'src/main.js': 'vue',
        'src/main.ts': 'vue-ts',
        'angular.json': 'angular'
    }

    spa_info = {}

    for indicator, spa_type in spa_indicators.items():
        file_path = page_dir / indicator
        if file_path.exists():
            spa_info['type'] = spa_type
            spa_info['entry_point'] = indicator

            # Try to read config information
            if indicator == 'package.json':
                try:
                    with open(file_path, 'r') as f:
                        package_data = json.load(f)
                        spa_info['name'] = package_data.get('name', page_dir.name)
                        spa_info['scripts'] = package_data.get('scripts', {})
                        spa_info['dependencies'] = package_data.get('dependencies', {})
                except:
                    pass

            # Determine assets directory
            if spa_type in ['built', 'react']:
                spa_info['assets_dir'] = str(page_dir / ('dist' if spa_type == 'built' else 'build'))
            else:
                spa_info['assets_dir'] = str(page_dir)

            log_verbose(f"Detected SPA in {page_dir}: {spa_info}")
            return spa_info

    return None

async def discover_pages() -> List[PageConfig]:
    """Discover all types of pages: static HTML, SPAs, and configured services"""
    discovered_pages = []

    # Check multiple directories for different types of content
    directories_to_check = [
        (Path.cwd() / "static", "static"),      # Traditional static HTML
        (Path.cwd() / "apps", "spa"),           # SPAs and complex apps
        (Path.cwd() / "pages", "static"),       # Alternative static location
        (Path.cwd() / "sites", "spa"),          # Alternative SPA location
    ]

    for base_dir, default_type in directories_to_check:
        if not base_dir.exists():
            log_verbose(f"Directory {base_dir} does not exist, skipping")
            continue

        log_verbose(f"Scanning {base_dir} for {default_type} content")

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
                spa_info = await detect_spa_type(item)

                if spa_info:
                    # It's a SPA
                    page_config = await create_spa_page_config(item, spa_info)
                    discovered_pages.append(page_config)
                else:
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

async def create_spa_page_config(spa_dir: Path, spa_info: Dict[str, Any]) -> PageConfig:
    """Create PageConfig for Single Page Applications"""
    page_name = spa_dir.name
    title = spa_info.get('name', page_name).replace('_', ' ').replace('-', ' ').title()

    return PageConfig(
        name=page_name,
        title=title,
        type="spa",
        entry_point=spa_info['entry_point'],
        assets_dir=spa_info['assets_dir'],
        color=generate_color_from_name(page_name),
        icon="⚛️" if 'react' in spa_info.get('type', '') else "🌐",
        auto_discovered=True,
        config_file=spa_info.get('config_file')
    )

async def extract_title_from_html(html_file: Path) -> Optional[str]:
    """Extract title from HTML file's <title> tag"""
    try:
        content = await asyncio.to_thread(html_file.read_text, encoding='utf-8')

        import re
        title_match = re.search(r'<title[^>]*>(.*?)</title>', content, re.IGNORECASE | re.DOTALL)
        if title_match:
            title = title_match.group(1).strip()
            log_verbose(f"Extracted title '{title}' from {html_file.name}")
            return title
    except Exception as e:
        log_verbose(f"Could not extract title from {html_file.name}: {e}")

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
    """Get all pages: manually configured + auto-discovered"""

    # You can add manual configurations here
    manual_pages = []

    # Auto-discover all types of pages
    discovered_pages = await discover_pages()

    # Combine and deduplicate
    all_pages = manual_pages.copy()
    manual_names = {page.name for page in manual_pages}

    for discovered_page in discovered_pages:
        if discovered_page.name not in manual_names:
            all_pages.append(discovered_page)
        else:
            log_verbose(f"Skipping auto-discovered page '{discovered_page.name}' - already manually configured")

    log_verbose(f"Total pages: {len(manual_pages)} manual + {len([p for p in all_pages if p.auto_discovered])} auto-discovered = {len(all_pages)}")

    return all_pages

# Global pages cache
PAGES: List[PageConfig] = []

@app.on_event("startup")
async def startup_event():
    """Initialize pages on startup"""
    global PAGES
    PAGES = await get_all_pages()
    log_verbose(f"Initialized with {len(PAGES)} total pages")

# FIXED: Only mount assets for non-HTML files to avoid conflicts
# This serves CSS, JS, images, etc. but NOT HTML files
class HTMLFilteredStaticFiles(StaticFiles):
    """StaticFiles that excludes HTML files to prevent template conflicts"""

    async def get_response(self, path: str, scope):
        if path.endswith('.html'):
            # Don't serve HTML files through static mount
            return None
        return await super().get_response(path, scope)

app.mount("/assets", HTMLFilteredStaticFiles(directory="static"), name="static_assets")

# Mount SPA assets directories dynamically based on discovered SPAs
@app.on_event("startup")
async def setup_spa_mounts():
    """Setup static file mounts for discovered SPAs"""
    for page in PAGES:
        if page.type == "spa" and page.assets_dir:
            assets_path = Path(page.assets_dir)
            if assets_path.exists():
                try:
                    app.mount(f"/spa-assets/{page.name}",
                             StaticFiles(directory=str(assets_path)),
                             name=f"spa_assets_{page.name}")
                    log_verbose(f"Mounted SPA assets for {page.name} at /spa-assets/{page.name}")
                except Exception as e:
                    log_verbose(f"Failed to mount assets for {page.name}: {e}")

# Template environments - more flexible setup
templates = Jinja2Templates(directory="templates")

# Dynamic template environments for different directories
template_envs = {}

async def get_template_env(directory: str) -> Jinja2Templates:
    """Get or create a Jinja2Templates environment for a specific directory"""
    if directory not in template_envs:
        dir_path = Path(directory)
        if dir_path.exists():
            template_envs[directory] = Jinja2Templates(directory=directory)
            log_verbose(f"Created template environment for {directory}")
        else:
            # Fallback to main templates directory
            template_envs[directory] = templates

    return template_envs[directory]

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Main container page that lists all available pages"""
    container_template = None

    # Look for container template in multiple locations
    for template_dir in ["index", "templates", "."]:
        template_path = Path(template_dir) / "container.html"
        if template_path.exists():
            env = await get_template_env(template_dir)
            container_template = env
            break

    if not container_template:
        # Create a simple default container if none exists
        return HTMLResponse(f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>App Container</title>
            <style>
                body {{ font-family: system-ui, sans-serif; margin: 2rem; }}
                .page-list {{ display: grid; gap: 1rem; max-width: 800px; }}
                .page-card {{ 
                    border: 1px solid #ddd; border-radius: 8px; padding: 1rem; 
                    text-decoration: none; color: inherit; display: block;
                    transition: transform 0.2s, box-shadow 0.2s;
                }}
                .page-card:hover {{ transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.1); }}
                .page-title {{ margin: 0 0 0.5rem 0; color: #333; }}
                .page-type {{ color: #666; font-size: 0.9rem; }}
            </style>
        </head>
        <body>
            <h1>Available Pages</h1>
            <div class="page-list">
                {''.join([f'''
                <a href="/page/{page.name}" class="page-card">
                    <h3 class="page-title">{page.icon or ''} {page.title}</h3>
                    <p class="page-type">Type: {page.type}</p>
                </a>
                ''' for page in PAGES])}
            </div>
        </body>
        </html>
        """)

    return container_template.TemplateResponse("container.html", {
        "request": request,
        "pages": PAGES
    })

@app.get("/refresh-pages")
async def refresh_pages():
    """Endpoint to refresh the pages list"""
    global PAGES
    old_count = len(PAGES)
    PAGES = await get_all_pages()
    log_verbose(f"Refreshed pages list - was {old_count}, now {len(PAGES)} total pages")
    return {
        "message": f"Refreshed {len(PAGES)} pages",
        "pages": [asdict(p) for p in PAGES]
    }

@app.get("/page/{page_name}")
async def get_page(page_name: str, request: Request):
    """Serve a specific page based on its type"""
    page = next((p for p in PAGES if p.name == page_name), None)
    if not page:
        log_verbose(f"Page not found: {page_name}")
        raise HTTPException(status_code=404, detail="Page not found")

    log_verbose(f"Serving page: {page_name} (type: {page.type})")

    if page.type == "static":
        # FIXED: Use the stored template_dir instead of guessing
        template_dir = page.template_dir or "static"
        log_verbose(f"Using template dir: {template_dir}, template: {page.template}")

        # Verify the template file exists
        template_path = Path(template_dir) / page.template
        if not template_path.exists():
            log_verbose(f"Template file not found: {template_path}")
            raise HTTPException(status_code=404, detail=f"Template file not found: {page.template}")

        # Get the template environment for this directory
        template_env = await get_template_env(template_dir)

        # Render the template
        return template_env.TemplateResponse(page.template, {
            "request": request,
            "page": page
        })

    elif page.type == "spa":
        # For SPAs, serve the entry point and let the SPA handle routing
        entry_path = Path(page.assets_dir) / page.entry_point
        if entry_path.exists():
            # For HTML entry points, process through template engine to inject config
            if entry_path.suffix == '.html':
                template_env = await get_template_env(str(entry_path.parent))
                return template_env.TemplateResponse(entry_path.name, {
                    "request": request,
                    "page": page,
                    "spa_base_url": f"/spa-assets/{page.name}/",
                    "api_base_url": f"/api/{page.name}/"
                })
            else:
                # For JS entry points, serve directly
                return FileResponse(entry_path)
        else:
            raise HTTPException(status_code=404, detail=f"SPA entry point not found: {page.entry_point}")

    elif page.type == "service":
        # Proxy to external service
        async with httpx.AsyncClient() as client:
            try:
                log_verbose(f"Proxying to service: {page.service_url}{page.path}")
                response = await client.request(
                    method=request.method,
                    url=f"{page.service_url}{page.path}",
                    headers=dict(request.headers),
                    content=await request.body(),
                    params=dict(request.query_params)
                )
                return Response(
                    content=response.content,
                    status_code=response.status_code,
                    headers=dict(response.headers)
                )
            except Exception as e:
                log_verbose(f"Service {page_name} unavailable: {e}")
                raise HTTPException(status_code=502, detail=f"Service {page_name} unavailable")

@app.api_route("/api/{page_name:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_api(page_name: str, request: Request):
    """Proxy API requests to services or SPA backends"""
    page_parts = page_name.split('/')
    page_name = page_parts[0]
    sub_path = '/' + '/'.join(page_parts[1:]) if len(page_parts) > 1 else '/'

    page = next((p for p in PAGES if p.name == page_name), None)
    if not page:
        raise HTTPException(status_code=404, detail="Service not found")

    if page.type == "service" and page.service_url:
        url = f"{page.service_url}{sub_path}"
        log_verbose(f"Proxying API request to: {url}")

        async with httpx.AsyncClient() as client:
            try:
                response = await client.request(
                    method=request.method,
                    url=url,
                    headers=dict(request.headers),
                    content=await request.body(),
                    params=dict(request.query_params)
                )
                return Response(
                    content=response.content,
                    status_code=response.status_code,
                    headers=dict(response.headers)
                )
            except Exception as e:
                log_verbose(f"Service unavailable: {url} - {e}")
                raise HTTPException(status_code=502, detail="Service unavailable")

    elif page.type == "spa":
        # For SPAs, you might want to proxy to a local dev server or API
        # This is a placeholder - implement based on your SPA's needs
        raise HTTPException(status_code=501, detail=f"API proxy not configured for SPA: {page_name}")

    else:
        raise HTTPException(status_code=400, detail="API proxy not supported for this page type")

if __name__ == "__main__":
    import uvicorn

    # Setup directories
    cwd = Path.cwd()
    directories = ["templates", "static", "apps", "pages", "sites", "index"]

    for dir_name in directories:
        (cwd / dir_name).mkdir(exist_ok=True)

    print("Starting enhanced containerizer...")
    print(f"Created directories: {', '.join(directories)}")
    print(f"Verbose logging: {'ON' if VERBOSE_LOGGING else 'OFF'}")
    print("Supports: Static HTML, SPAs (React/Vue/Angular/Vanilla), and Microservices")
    print("Visit /refresh-pages to reload during development")

    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")