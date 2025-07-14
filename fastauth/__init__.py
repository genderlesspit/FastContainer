from pathlib import Path

from starlette.templating import Jinja2Templates

from .server import AuthServer
from .oauth_token_manager import ManagedOAuthClient, MultiTenantTokenManager, TokenStorage, GraphAPI, AccessToken, PKCEChallenge
import inspect
from loguru import logger as log

class Dummy:
    foo = "bar"

_frame = inspect.currentframe()
_info = inspect.getframeinfo(_frame)
_filename = _info.filename
cwd = Path(_filename).parent

template_dir = str(Path(cwd / "templates"))
log.debug(f"Constructed template dir at {template_dir}")
templates = Jinja2Templates(directory=template_dir)

auth_server = AuthServer()
auth_server.thread.start()