import asyncio
import threading
import tomllib as toml
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from tabnanny import verbose
from types import SimpleNamespace
import json
from typing import Any, Dict, Type

import jsonschema
from fastapi import FastAPI
from pydantic.v1.typing import new_type_supertype
#from pywershell import PywershellLive
from singleton_decorator import singleton
from loguru import logger as log
from pydantic import BaseModel
from typing import Dict, Any
import threading
from loguru import logger as log

### CFG SCHEMA ###

@dataclass
class MicroserviceSchema:
    host: str
    port: int
    url: str = None

    def __post_init__(self):
        if self.url is None:
            self.url = f"http://{self.host}:{self.port}"

class ConfigSchema(BaseModel):
    microservices: list[MicroserviceSchema]

    @classmethod
    def from_dict(cls, schema):
        microservices = []
        for key in schema:
            val = schema[key]
            ms = MicroserviceSchema(**val)
            microservices.append(ms)

        return ConfigSchema(
            microservices=microservices
        )

#for documentation purposes
example_schema = {
    "microservice": {
        "host": "localhost",
        "port": "1234"
    }
}

load_cfg = ConfigSchema.from_dict

######

@singleton
class MicroservicesManager:
    microservices: list[MicroserviceSchema]

    def __init__(self, dir: Path = Path.cwd()):
        self.dir = dir
        _, _ = self.paths, self.config

    @cached_property
    def paths(self) -> SimpleNamespace:
        self.dir.mkdir(exist_ok=True)
        cfg = self.dir / "microservices.toml"
        cfg.touch(exist_ok=True)
        return SimpleNamespace(
            cfg=cfg
        )

    @cached_property
    def config(self):
        cfg_path = self.paths.cfg
        data = toml.load(cfg_path)
        cfg = load_cfg(data)
        self.microservices = cfg.microservices
        return cfg


class Microservice(FastAPI):
    def __init__(self):
        super().__init__()

    def launch(self):
        pass

@singleton
class ThreadManager:
    """
    Singleton for managing all ManagedThread instances.
    """
    __slots__ = ('verbose', 'threads')

    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self.threads: Dict[str, threading.Thread] = {}

    def register(self, thread: threading.Thread) -> None:
        """Register a new managed thread."""
        self.threads[thread.obj_full_name] = thread
        if self.verbose:
            log.debug(f"[{self}]: Registered thread '{thread.name}' (id={thread.obj_id})")
        return thread

    def unregister(self, thread: threading.Thread) -> None:
        """Unregister a managed thread once it’s done."""
        self.threads.pop(thread.name, None)
        if self.verbose:
            log.debug(f"[{self}]: Unregistered thread '{thread.name}'")

    def __getitem__(self, name: str) -> threading.Thread:
        """Retrieve a thread by its name."""
        return self.threads.get(name)


class _ManagedThread:
    """
    Thread subclass that auto-registers itself in ThreadManager.
    Usage:
        inst = ManagedThread(some_callable, arg1, arg2, kw=value)
        inst.start()
    """
    def __init__(self, obj, *args, **kwargs):
        self.obj = obj
        self.obj_name = getattr(obj, '__name__', repr(obj))
        self.obj_id = id(obj)
        self.obj_full_name = f"{self.obj_name}-{self.obj_id}"
        self.args = args
        self.kwargs = kwargs

    @cached_property
    def _thread(self):
        inst = threading.Thread(
            target=self.obj,
            name=self.obj_full_name,
            args=self.args,
            kwargs=self.kwargs,
            daemon=True
        )
        inst.obj = self.obj
        inst.obj_name = self.obj_name
        inst.obj_id = self.obj_id
        inst.obj_full_name = self.obj_full_name
        inst.__name__ = self.obj_name

        for attr, val in vars(self.obj).items():
            if not attr.startswith('__') and not hasattr(self, attr):
                setattr(self, attr, val)

        return inst

    @classmethod
    def _decorator(cls, obj, *args, **kwargs):
        mgr = ThreadManager()
        inst = cls(obj, *args, **kwargs)
        if inst.obj_full_name in mgr.threads:
            return mgr.threads[inst.obj_full_name]
        else:
            mgr.register(inst._thread)
        return mgr[inst.obj_full_name]

ManagedThread = _ManagedThread._decorator

@ManagedThread
def foo():
    print("bar")

foo.start()

@ManagedThread
class Microservice1:
    foo = "bar1"

    def __new__(cls, *args, **kwargs):
        print(cls.foo)

Microservice1.start()

@ManagedThread
class Microservice2:
    foo = "bar2"

log.debug(Microservice2.__dict__)

#help(Microservice2)

# class NetStat:
#     def __init__(self):
#         self.pywershell = PywershellLive()
#
#     @property
#     async def active_connections(self):
#         # script_path = Path.cwd() / "netstat.ps1"
#         return await self.pywershell.run([f"netstat -c"])
#
#     @property
#     async def grep(self):
#         return await self.pywershell.run("netstat -ano | findstr '15716'")
#
# async def debug():
#     await NetStat().active_connections
#     await NetStat().grep

#