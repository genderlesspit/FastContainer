from loguru import logger as log

from .import_context import get_import_chain, Caller

# caller_frame = get_import_chain(verbose=True)
# current = Caller(**caller_frame) if caller_frame.__class__ is dict else None
# log.debug(Caller.__dict__)

def get_caller() -> Caller | None:
    caller_frame = get_import_chain(verbose=True) #type: ignore
    return Caller(**caller_frame) if caller_frame.__class__ is dict else None