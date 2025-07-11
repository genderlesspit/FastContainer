import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any

from loguru import logger as log


@dataclass
class Caller:
    depth: int
    filename: str
    name: str
    function: str
    line: int
    is_frozen: bool
    is_init: bool
    code: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Caller':
        """Create Caller from dictionary (supports **dict unpacking)"""
        return cls(**data)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return asdict(self)  # type: ignore


def get_import_chain(verbose: bool = False) -> dict | list:
    """Get the full import chain for debugging"""
    stack = inspect.stack()
    chain = []

    for i, frame_info in enumerate(stack[1:], 1):
        filepath = Path(frame_info.filename)

        frame_data = {
            'depth': i,
            'filename': frame_info.filename,
            'name': filepath.name,
            'function': frame_info.function,
            'line': frame_info.lineno,
            'is_frozen': frame_info.filename.startswith('<frozen'),
            'is_init': filepath.name == '__init__.py',
            'code': frame_info.code_context[0].strip() if frame_info.code_context else None
        }

        chain.append(frame_data)

        status = "SKIP" if (frame_data['is_frozen'] or frame_data['is_init']) else "TARGET"
        if verbose: log.debug(
            f"Frame {i}: [{status}] {frame_data['name']}:{frame_data['line']} in {frame_data['function']}")

        if status == "TARGET":
            return frame_data

    log.warning(f"Could not find the correct chain, returning full stack.")
    return chain
