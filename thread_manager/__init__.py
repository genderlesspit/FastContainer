import threading
from functools import cached_property
from typing import Dict, Type, Any
from loguru import logger as log

from singleton_decorator import singleton


@singleton
class _ThreadManager:
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
    Thread subclass that auto-registers itself in _ThreadManager.
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
    def _thread(self) -> threading.Thread | Type:
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
        return new_obj

    @classmethod
    def _decorator(cls, obj, *args, **kwargs) -> Type | threading.Thread:
        mgr = _ThreadManager()
        inst = cls(obj, *args, **kwargs)
        if inst.obj_full_name in mgr.threads:
            return mgr.threads[inst.obj_full_name]
        else:
            mgr.register(inst._thread)
        return mgr[inst.obj_full_name]

ManagedThread = _ManagedThread._decorator
manager = _ThreadManager()