from typing import Optional

import aiohttp
from loguru import logger as log
from sqlalchemy import select

from back_end.database.sqlite_manager import Database
from back_end.receptionist.models import (
    RequestEntry,
    Routes,
    recep_resp,
    recep_request,
    RequestEntryDC, RequestEntrySQL, RequestLog, CallbackEntry,
)

class ReceptionistManager:
    instances = {}

    @classmethod
    def inst(cls, recep):
        from back_end.receptionist.factory import Receptionist
        recep: Receptionist
        if recep.name not in cls.instances:
            cls.instances[recep.name] = cls(recep)
        return cls.instances[recep.name]

    def __init__(self, recep):
        from back_end.receptionist.factory import Receptionist
        self.recep: Receptionist = recep
        self.routes: Routes = recep.api_routes
        self.headers = recep.api_headers
        self.rlog = RequestLog(self)

        if recep.db:
            if recep.callback:
                self.db = Database(
                    project=recep.project,
                    name=recep.name,
                    dir=recep.dir,
                    input_model=[RequestEntrySQL, CallbackEntrySQL] #type: ignore
                )
                self.callback_table = self.db.manager.models.callbackentrysql
            else: self.db = Database(
                project=recep.project,
                name=recep.name,
                dir=recep.dir,
                input_model=RequestEntrySQL #type: ignore
            )
            from back_end.database.sqlite_manager import DatabaseManager
            self.manager: DatabaseManager = self.db.manager
            self.table: RequestEntrySQL = self.manager.models.requestentrysql
        elif recep.redis:
            if recep.callback:
                self.redis_callback = RedisManager(CallbackEntry, "callback_entry" )
            self.redis = RedisManager(RequestEntry, "recep_entry")
        else:
            raise RuntimeError("Receptionist must have either db or redis backend.")
        self.backend = self.db if hasattr(self, "db") else self.redis
        log.success(f"{self} Successfully initialized: \n- backend_mode={self.backend.__class__.__name__}\n- callback_mode={self.recep.callback}")

    def __repr__(self):
        if self.recep.callback: return f"[{self.recep.name.title()}.Receptionist] <callback_mode=True>"
        return f"[{self.recep.name.title()}.Receptionist]"

    async def request(self, method: str, route: str, append: str = "", format: dict = None,
                      force_refresh: bool = False, **kw) -> Optional[recep_resp]:
        try:
            path = self.routes[route]
        except KeyError:
            path = route

        if format:
            path = path.format(**format)
        if append:
            path += append

        if force_refresh is False:
            cached = self._get_cache(path)
            if cached:
                log.debug(f"{self}: Cache HIT for {path}")
                return cached

        request = recep_request(method=method, route=path, headers=self.headers.index)
        log.debug(f"{self}: {method.upper()} {path} | HEADERS={self.headers.index} | KWARGS={kw}")

        async with aiohttp.ClientSession(headers=request.headers) as ses:
            async with ses.request(method.upper(), path, **kw) as res:
                try:
                    content_type = res.headers.get("Content-Type", "")
                    if "json" in content_type:
                        content = await res.json()
                    else:
                        content = await res.text()
                except Exception as e:
                    content = await res.text()  # always fallback
                    log.warning(f"{self}: Bad response decode → {e} | Fallback body: {content}")

                out = recep_resp(
                    status_code=res.status,
                    headers=dict(res.headers),
                    body=content
                )
                self.rlog.log(req=request, resp=out)

                self._store_cache(RequestEntryDC(
                    status=out.status_code,
                    method=method,
                    headers=self.headers.index,
                    url=path,
                    body=kw.get("json") or kw.get("data"),
                    response=out.body
                ))

                return out

    def _store_cache(self, entry: RequestEntryDC):
        if hasattr(self, "db"):
            self.table.c(entry.to_json())
        if hasattr(self, "redis"):
            self.redis.create(entry.url, entry.to_json())

    def _get_cache(self, url: str) -> Optional[recep_resp]:
        if hasattr(self, "db"):
            with self.manager.session() as s:
                row = self.table.r({"url": url}, session=s)
                if row:
                    dc = RequestEntryDC.from_sql(sql=row)
                    return recep_resp(
                        status_code=dc.status,
                        headers=dc.headers or {},
                        body=dc.response,
                        received_at=dc.timestamp
                    )
        if hasattr(self, "redis"):
            cached = self.redis.read(url)
            if cached:
                dc = RequestEntryDC.from_json(cached)
                return recep_resp(
                    status_code=dc.status,
                    headers=dc.headers or {},
                    body=dc.response,
                    received_at=dc.timestamp
                )
        return None

    async def get(self, route, append=None, format=None, force_refresh=False, **kw):
        return await self.request("get", route, append=append, format=format, force_refresh=force_refresh, **kw)

    async def post(self, route, append=None, format=None, force_refresh=False, **kw):
        return await self.request("post", route, append=append, format=format, force_refresh=force_refresh, **kw)

    async def put(self, route, append=None, format=None, force_refresh=False, **kw):
        return await self.request("put", route, append=append, format=format, force_refresh=force_refresh, **kw)

    async def delete(self, route, append=None, format=None, force_refresh=False, **kw):
        return await self.request("delete", route, append=append, format=format, force_refresh=force_refresh, **kw)

    async def callback(self, event: str, payload: dict | str, source: str | None = None, status_code: int = 200, method: str = "callback", url: str = "callback/internal") -> None:
        from back_end.receptionist.models import CallbackEntryDC

        entry = CallbackEntryDC(
            status=status_code,
            method=method,
            headers=self.headers.index,
            url=url,
            body=payload,
            response=payload,
            event=event,
            source=source
        )

        if self.recep.callback:
            if hasattr(self, "callback_table"): self.callback_table.c(entry.to_json())
            elif hasattr(self, "redis_callback"): await self.redis_callback.create(f"{event}:{url}", entry.to_json())
            else: log.warning(f"{self}: Callback enabled but no storage backend found.")
        else: log.warning(f"{self}: Callback method called but callback mode is off.")