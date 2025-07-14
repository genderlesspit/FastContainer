from pathlib import Path
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

auth_server = AuthServer()
auth_server.thread.start()