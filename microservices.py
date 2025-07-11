import re
import inspect
import re
import threading
import tomllib as toml
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from threading import Thread
from types import SimpleNamespace
from typing import Any
from typing import Dict
from typing import Type

from fastapi import FastAPI
from loguru import logger as log
from pydantic import BaseModel
# from pywershell import PywershellLive
from singleton_decorator import singleton

### CFG SCHEMA ###

STUB_MARK = "!@#$%^STUBGENED!@#$%^"

def simple_stub(obj: Any, *, write: bool = True) -> str | None:
    """
    Generate or update a dumb stub for obj, wrapping it in delimiters
    so only that section ever gets overwritten.
    """
    # 1) Build the raw stub (same as simple_stub)
    if isinstance(obj, threading.Thread): return None

    name = getattr(obj, "__name__", obj.__class__.__name__)
    lines = [f"class {name}:"]
    for attr in dir(obj):
        if attr.startswith("_"): continue
        try: val = getattr(obj, attr)
        except:
            lines.append(f"    {attr}: Any")
            continue
        if callable(val):
            lines.append(f"    def {attr}(*args, **kwargs) -> Any: ...")
        else:
            lines.append(f"    {attr}: Any")
    if len(lines) == 1:
        lines.append("    pass")
    raw_stub = "\n".join(lines) + "\n"

    # 2) Wrap with START/END markers
    start = f"# {STUB_MARK} START {name}\n"
    end   = f"# {STUB_MARK} END   {name}\n"
    block = start + raw_stub + end

    if write:
        mod = inspect.getsourcefile(obj)
        pyi = Path(mod.__file__).with_suffix(".pyi") if mod and hasattr(mod, "__file__") \
              else Path(f"{name}.pyi")

        text = pyi.read_text() if pyi.exists() else ""
        # regex to find existing block
        pattern = re.compile(
            rf"# {re.escape(STUB_MARK)} START {re.escape(name)}.*?"
            rf"# {re.escape(STUB_MARK)} END   {re.escape(name)}\n",
            re.DOTALL
        )
        if pattern.search(text):
            new_text = pattern.sub(block, text)
        else:
            # append at end with a blank line
            new_text = text.rstrip() + "\n\n" + block

        pyi.write_text(new_text)
        print(f"[stub_with_markers] updated {name} in {pyi}")

    return block

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
        self.threads: Dict[str, Type | threading.Thread] = {}

    def register(self, thread: Type) -> None:
        """Register a new managed thread."""
        self.threads[thread.obj_full_name] = thread
        if self.verbose:
            log.debug(f"[{self}]: Registered thread '{thread.name}' (id={thread.obj_id})")
        return thread

    def unregister(self, thread: Type) -> None:
        """Unregister a managed thread once it’s done."""
        self.threads.pop(thread.name, None)
        if self.verbose:
            log.debug(f"[{self}]: Unregistered thread '{thread.name}'")

    def __getitem__(self, name: str) -> Type:
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

    @staticmethod
    def mixins(*mixins: Any, cls: Type) -> Type | threading.Thread:
        """
        Dynamically create a new version of `cls` whose bases
        are (valid_mixins..., original bases). Rejects any mixin
        that isn’t a class.
        """
        # 1) Reject non‐class mixins
        invalid = [m for m in mixins if not isinstance(m, type)]
        if invalid:
            names = ", ".join(repr(m) for m in invalid)
            raise TypeError(f"Cannot mix in non‐class objects: {names}")

        # 2) Collect cls body
        orig_dict = {
            k: v for k, v in cls.__dict__.items()
            if k not in ("__dict__", "__weakref__")
        }

        # 3) Build new MRO: mixins first, then existing bases
        new_bases: Tuple[type, ...] = mixins + cls.__bases__  # type: ignore

        # 4) Python picks the right metaclass automatically
        return type(cls.__name__, new_bases, orig_dict)

    @cached_property
    def _thread(self) -> Thread | Type:
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

        # for attr, val in vars(self.obj).items():
        #     if not attr.startswith('__') and not hasattr(self, attr):
        #         setattr(self, attr, val)

        new_obj = None
        try:
            new_obj = self.mixins(inst, cls=self.obj)
        except TypeError: new_obj = inst
        if new_obj is None: raise RuntimeError
        simple_stub(new_obj)
        return new_obj

    @classmethod
    def _decorator(cls, obj, *args, **kwargs) -> Type | Thread:
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