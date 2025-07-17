from typing import Any, Union
from loguru import logger as log

class _Annotations:
    """Mixin class for dynamic annotation management"""

    def __init__(self, **kwargs: Union[str, Any]):
        if not hasattr(self, '__annotations__'):
            self.__annotations__ = {}

        # Process annotation kwargs
        for k, v in kwargs.items():
            log.debug(f"Setting annotation {k} = {v}")
            self.__annotations__[k] = v

class _FlexDict(dict, _Annotations):
    """Enhanced response object with attribute access and verbose logging support"""

    def __init__(self, **kwargs: Union[str, Any]):
        dict.__init__(self)
        _Annotations.__init__(self, **kwargs)
        for each in self.__annotations__:
            self.__dict__[each] = None
            self.setdefault(each, None)

    def __getattr__(self, name: str) -> Any:
        if name in self:
            return self[name]
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith('_') or name in ['__annotations__']:
            super().__setattr__(name, value)
        else: self[name] = value

flexdict = _FlexDict
