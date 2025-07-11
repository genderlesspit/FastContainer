import ast
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import List, Dict

from loguru import logger as log
from singleton_decorator import singleton

from import_context import get_caller, Caller

# from .core import StubManager

REPR = "[StubManager]"
VERBOSE = True
CALLER = get_caller()
CALLER.PATH = Path(CALLER.filename)
CALLER.DIR = CALLER.PATH.parent


def pyi_path(path: Path):
    return CALLER.DIR / (path.name + "i")


CALLER.PYI = pyi_path(Path(CALLER.filename))
CALLER.PYI.touch(exist_ok=True)
DELIMITER_START = "#<!-- {name} START -->"
DELIMITER_STOP = "#<!-- {name} STOP -->"


def named_delimiter(name: str, stop: bool = False) -> str:
    delimiter = DELIMITER_STOP if stop else DELIMITER_START
    return delimiter.format(name=name)


def detect_objects() -> List[ast.FunctionDef | ast.ClassDef]:
    with open(CALLER.filename, 'r') as f:
        tree = ast.parse(f.read())

    nodes = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef) or isinstance(node, ast.FunctionDef):
            if VERBOSE: log.debug(f"[StubManager]: Object '{node.name}' identified in {CALLER.filename}.")
            nodes.append(node)
            # body: ast.Assign = list(node.__dict__["body"]).__getitem__(0)
            ast.unparse(node)
    return nodes


imported_objects = detect_objects()


def stub_from_def_node(node: ast.FunctionDef | ast.ClassDef):
    name: str = node.name
    log.debug(f"{REPR}: Attempting to detect stub for {name}")
    unparsed: str = ast.unparse(node)
    start_delimiter: str = named_delimiter(name=name, stop=False)
    stop_delimiter: str = named_delimiter(name=name, stop=True)
    start_line: int | None = None
    stop_line: int | None = None

    with open(CALLER.PYI, 'r', encoding="utf-8") as f:
        for i, line in enumerate(f):
            if VERBOSE: log.debug(f"{i}: {line.strip()}")
            if start_delimiter in line:
                if start_line: raise RuntimeWarning
                start_line = i
            if stop_delimiter in line:
                if stop_line: raise RuntimeWarning
                stop_line = i
            if start_line and stop_line:
                if VERBOSE: log.debug(
                    f"{REPR}: Detected {start_delimiter} at lineno.{start_line} and {stop_line} at {stop_delimiter}")
                break

    if start_line is None and stop_line is None:
        log.warning(f"{REPR}: Could not find stub for {name}... Generating...")
        with open(CALLER.PYI, 'a', encoding="utf-8") as f:
            f.write(f"{start_delimiter}\n")
            f.write(f"{unparsed}\n")
            f.write(f"{stop_delimiter}\n")
        log.debug(f"{REPR}: Successfully wrote stub for {name}")

    elif start_line is None and stop_line is not None:
        raise RuntimeError(f"{REPR}: Found stop delimiter without start")

    elif start_line is not None and stop_line is None:
        raise RuntimeError(f"{REPR}: Found start delimiter without stop")

    elif start_line is not None and stop_line is not None:
        log.debug(f"{REPR}: Found delimiters at {start_line, stop_line}")
        raise NotImplementedError


for each in imported_objects:
    stub_from_def_node(each)


@dataclass
class _StubbedObject:
    key: str
    obj: callable
    name: str
    called_from: Caller = None
    obj_stub: str = None
    obj_path: Path = None

    def __repr__(self):
        return f"[{self.name}.pyi]"

    def __post_init__(self):
        self.called_from = CALLER
        self.obj_path: Path = self._path_factory
        _ = StubManager[self.obj]

    @cached_property
    def _path_factory(self) -> Path:
        path = Path(self.called_from.filename)
        root = path.parent
        file_name = (self.called_from.name + "i")
        new_path = root / file_name
        if VERBOSE: log.debug(f"{self}: Set stub path as {new_path}")
        return new_path


@singleton
class _StubManager:

    def __init__(self):
        self.objs: Dict[str | _StubbedObject] = {}  # type: ignore

    def __setitem__(self, obj: callable):
        stubbed_obj_map = {}
        som = stubbed_obj_map
        som["obj"] = obj
        som["name"] = obj.__name__
        som["key"] = f"{Path(CALLER.filename).name}.{obj.__name__}"
        self.objs[som["key"]] = _StubbedObject(**som)
        if VERBOSE: log.success(f"{self}: Successfully initialized stub object for {som["name"]}")
        return self.objs[som["key"]]

    def __getitem__(self, obj: callable):
        if f"{Path(CALLER.filename).name}.{obj.__name__}" in self.objs:
            if VERBOSE: log.warning(f"{self}: StubbedObject not yet created for {obj.__name__}")
            return self.objs[f"{Path(CALLER.filename).name}.{obj.__name__}"]
        return self.__setitem__(obj)


StubManager = _StubManager()
