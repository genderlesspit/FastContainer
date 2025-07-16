from dataclasses import dataclass, field
from pathlib import Path

from back_end.receptionist.models import headers, routes, RequestLog
# from mileslib_infra import Project
from loguru import logger as log


@dataclass
class Receptionist:
    """
    Receptionist orchestrates outbound requests and optional callback capture.

    Attributes:
        project (Project): Reference to the parent project context.
        name (str): Unique name for the receptionist instance.
        dir (Path): Directory to store any associated cache/log/state files.
        callback (bool): If True, enables callback capture and storage logic.
        headers (headers): Default api_headers to use for outbound requests.
        routes (routes): Route mappings for outbound requests.
        redis (bool): If True, uses Redis for request/callback storage.
        db (bool): If True, uses SQLite for request/callback storage.
        manager (ReceptionistManager): Auto-initialized backend manager for this instance.
    """
    from back_end.receptionist.core import ReceptionistManager
    # project: Project
    name: str
    dir: Path
    callback: bool = False
    headers: headers = field(default_factory=lambda: headers(index={}))
    routes: routes = field(default_factory=lambda: routes(base="", routes={}))
    redis: bool = False
    db: bool = False
    manager: ReceptionistManager = None

    def __repr__(self):
        return f"[{self.name}.Receptionist]"

    def __post_init__(self):
        self.dir.mkdir(exist_ok=True)
        if self.db and self.redis or not self.db and self.redis: log.warning(f"{self}: You need to choose either DB or Redis for storage type! Defaulting to redis...")
        if not self.headers or not self.routes: log.warning(f"{self}: <self.api_headers={self.headers}> <api_routes={self.routes}>\n\n--RECEPTIONIST HELP--\nTry using initializing with api_headers of urls for easier request construction!\n")
        from back_end.receptionist.core import ReceptionistManager
        self.manager = ReceptionistManager.inst(self)
        if not self.manager: raise RuntimeError(f"{self}: Failed to initialize self.manager!")