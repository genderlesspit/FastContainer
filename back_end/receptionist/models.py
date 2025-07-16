from dataclasses import dataclass, asdict
from dataclasses import field
from datetime import datetime
from typing import Dict, Any
from typing import Optional

from loguru import logger as log
from pydantic import BaseModel
from sqlalchemy import inspect
from sqlmodel import SQLModel, Field, Column, JSON, Session
from pydantic.dataclasses import dataclass as pydantic_dc

routes = Routes

@dataclass
class ReceptionistRequest:
    method: str
    route: str
    headers: dict
    body: dict | str | None = None

recep_request = ReceptionistRequest

@dataclass
class ReceptionistResponse:
    status_code: int
    headers: dict
    body: dict | str
    duration_ms: float | None = None
    received_at: datetime = field(default_factory=datetime.utcnow)

recep_resp = ReceptionistResponse

class RequestEntry(BaseModel):
    status: int
    method: str
    headers: dict | None
    url: str
    body: dict | str | None
    response: dict | str
    timestamp: datetime

    def __str__(self):
        preview = str(self.body)[:200].replace("\n", "")
        return f"[{self.timestamp.isoformat()}] {self.method.upper()} {self.url} → {self.status} | body={preview}"

@dataclass
class RequestEntryDC:
    status: int
    method: str
    headers: dict | None
    url: str
    body: dict | str | None
    response: dict | str
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_sql(self) -> "RequestEntrySQL":
        return RequestEntrySQL(
            status=self.status,
            method=self.method,
            headers=self.headers,
            url=self.url,
            body=self.body,
            response=self.response,
            timestamp=self.timestamp
        )

    @classmethod
    def from_sql(cls, sql: "RequestEntrySQL", session: Session | None = None) -> "RequestEntryDC":
        return cls(
            status=sql.status,
            method=sql.method,
            headers=sql.headers,
            url=sql.url,
            body=sql.body,
            response=sql.response,
            timestamp=sql.timestamp
        )

    def to_json(self) -> dict:
        return {
            "status": self.status,
            "method": self.method,
            "api_headers": self.headers,
            "url": self.url,
            "body": self.body,
            "response": self.response,
            "timestamp": self.timestamp.isoformat(),
        }

    @classmethod
    def from_json(cls, data: dict) -> "RequestEntryDC":
        return cls(
            status=data["status"],
            method=data["method"],
            headers=data.get("api_headers"),
            url=data["url"],
            body=data.get("body"),
            response=data["response"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
        )

recep_entry = RequestEntryDC

class RequestEntrySQL(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    status: int
    method: str
    headers: dict | None = Field(default=None, sa_column=Column(JSON))
    url: str
    body: dict | str | None = Field(default=None, sa_column=Column(JSON))
    response: dict | str = Field(sa_column=Column(JSON))
    timestamp: datetime = Field(default_factory=datetime.utcnow, index=True)

    def __str__(self):
        preview = str(self.body)[:200].replace("\n", "")
        return f"[{self.timestamp.isoformat()}] {self.method.upper()} {self.url} → {self.status} | body={preview}"


@dataclass
class RequestLog:
    #from back_end.receptionist.core import ReceptionistManager
    manager: Any #ReceptionistManager
    entries: list[RequestEntryDC] = field(default_factory=list)

    def log(self, req: ReceptionistRequest, resp: ReceptionistResponse):
        entry = RequestEntryDC(
            status=resp.status_code,
            method=req.method,
            headers=req.headers,
            url=req.route,
            body=req.body,
            response=resp.body
        )
        self.entries.append(entry)
        if entry.status == 200: log.success(f"{self}: {entry.status} | {entry.response}")
        else: log.warning(f"{self}: {entry.status} | {entry.response}")

    def __repr__(self):
        return f"{self.manager}.[RequestLog: {len(self.entries)} entries]"

# --- pydantic redis/json model ---
class CallbackEntry(BaseModel):
    status: int
    method: str
    headers: dict | None
    url: str
    body: dict | str | None
    response: dict | str
    event: str
    source: str | None
    timestamp: datetime

    def __str__(self):
        preview = str(self.body)[:200].replace("\n", "")
        return f"[{self.timestamp.isoformat()}] {self.event.upper()} {self.method.upper()} {self.url} ← {self.status} | source={self.source} | body={preview}"


# --- dataclass ---
@dataclass
class CallbackEntryDC:
    status: int
    method: str
    headers: dict | None
    url: str
    body: dict | str | None
    response: dict | str
    event: str
    source: str | None = None
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_sql(self) -> "CallbackEntrySQL":
        return CallbackEntrySQL(
            status=self.status,
            method=self.method,
            headers=self.headers,
            url=self.url,
            body=self.body,
            response=self.response,
            event=self.event,
            source=self.source,
            timestamp=self.timestamp
        )

    @classmethod
    def from_sql(cls, sql: "CallbackEntrySQL", session: Session | None = None) -> "CallbackEntryDC":
        return cls(
            status=sql.status,
            method=sql.method,
            headers=sql.headers,
            url=sql.url,
            body=sql.body,
            response=sql.response,
            event=sql.event,
            source=sql.source,
            timestamp=sql.timestamp
        )

    def to_json(self) -> dict:
        return {
            "status": self.status,
            "method": self.method,
            "api_headers": self.headers,
            "url": self.url,
            "body": self.body,
            "response": self.response,
            "event": self.event,
            "source": self.source,
            "timestamp": self.timestamp.isoformat()
        }

    @classmethod
    def from_json(cls, data: dict) -> "CallbackEntryDC":
        return cls(
            status=data["status"],
            method=data["method"],
            headers=data.get("api_headers"),
            url=data["url"],
            body=data.get("body"),
            response=data["response"],
            event=data["event"],
            source=data.get("source"),
            timestamp=datetime.fromisoformat(data["timestamp"])
        )


# --- sqlmodel ---
class CallbackEntrySQL(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    status: int
    method: str
    headers: dict | None = Field(default=None, sa_column=Column(JSON))
    url: str
    body: dict | str | None = Field(default=None, sa_column=Column(JSON))
    response: dict | str = Field(sa_column=Column(JSON))
    event: str
    source: str | None = None
    timestamp: datetime = Field(default_factory=datetime.utcnow, index=True)

    def __str__(self):
        preview = str(self.body)[:200].replace("\n", "")
        return f"[{self.timestamp.isoformat()}] {self.event.upper()} {self.method.upper()} {self.url} ← {self.status} | source={self.source} | body={preview}"


# --- optional runtime log tracker ---
@dataclass
class CallbackLog:
    manager: Any
    entries: list[CallbackEntryDC] = field(default_factory=list)

    def log(self, req, resp):
        entry = CallbackEntryDC(
            status=resp.status_code,
            method=req.method,
            headers=req.api_headers,
            url=req.route,
            body=req.body,
            response=resp.body,
            event=req.event,
            source=req.source
        )
        self.entries.append(entry)
        if entry.status == 200:
            log.success(f"{self}: {entry.status} | {entry.event} | {entry.response}")
        else:
            log.warning(f"{self}: {entry.status} | {entry.event} | {entry.response}")

    def __repr__(self):
        return f"{self.manager}.[CallbackLog: {len(self.entries)} entries]"