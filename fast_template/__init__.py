from pathlib import Path
from import_context import get_caller
from starlette.templating import Jinja2Templates
from loguru import logger as log

_DEBUG = True
REPR = "FastTemplate"
PREPR = f"[{REPR}]:"
SPREPR = f"[{REPR} ]:"
template_envs = {}

_CALLER = get_caller()
_CALLER_DIR: Path = Path(_CALLER.filename).parent / "templates"
_CALLER_DIR.mkdir(exist_ok=True)
_CALLER_DIR_POSIX: str = _CALLER_DIR.as_posix()
if _DEBUG: log.debug(f"{PREPR} Created directory at")

def _get_template_env(directory: str = _CALLER_DIR_POSIX) -> Jinja2Templates:
    """Get or create a Jinja2Templates environment for a specific directory"""
    if directory not in template_envs:
        dir_path = Path(directory)
        if dir_path.exists():
            template_envs[directory] = Jinja2Templates(directory=directory)
            log.debug(f"{PREPR} Created template environment for {directory}")
    return template_envs[directory]

FastTemplates = _get_template_env
FastTemplates.__await__ = _get_template_env
