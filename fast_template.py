from pathlib import Path

from starlette.templating import Jinja2Templates
from loguru import logger as log

template_envs = {}

async def get_template_env(directory: str) -> Jinja2Templates:
    """Get or create a Jinja2Templates environment for a specific directory"""
    if directory not in template_envs:
        dir_path = Path(directory)
        if dir_path.exists():
            template_envs[directory] = Jinja2Templates(directory=directory)
            log.debug(f"Created template environment for {directory}")

    return template_envs[directory]

FastTemplates = get_template_env