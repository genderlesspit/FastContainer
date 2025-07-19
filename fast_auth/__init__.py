import asyncio
import inspect
from pathlib import Path

from loguru import logger as log
from starlette.templating import Jinja2Templates

_frame = inspect.currentframe()
_info = inspect.getframeinfo(_frame)
_filename = _info.filename
CWD = Path(_filename).parent
TEMPLATE_DIR = str(Path(CWD / "templates"))
TEMPLATES = Jinja2Templates(directory=TEMPLATE_DIR)

log.debug(f"Constructed template dir at {TEMPLATE_DIR}\nobj={TEMPLATES}")

from .server import AuthServer
from .oauth_token_manager import ManagedOAuthClient, MultiTenantTokenManager, TokenStorage, GraphAPI, AccessToken, \
    PKCEChallenge

auth_server = AuthServer()

async def _init():
    await auth_server.azure_cli
    await auth_server.app_registration
    await auth_server.client_id

asyncio.run(_init())

auth_server.thread.start()

URL = auth_server.url

from .authed_server import FastAuth