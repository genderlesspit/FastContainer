import json
import uuid
from functools import singledispatch
from typing import Type

from sqlmodel import SQLModel, select, Session
from loguru import logger as log


def scrud(db, cls: Type[SQLModel]):
    cls._db = db

    def get_session(s: Session = None):
        return s or cls._db.session()

    # --- CREATE ---
    @singledispatch
    def _create(data, session: Session = None):
        raise TypeError(f".c() unsupported type: {type(data)}")

    @_create.register
    def _(data: dict, session: Session = None):
        with get_session(session) as s:
            obj = cls(**data)
            s.add(obj)
            s.commit()
            s.refresh(obj)
            log.success(f"[SCRUD] Created {cls.__name__}: {obj}")
            return obj

    @_create.register
    def _(data: str, session: Session = None):
        return _create(json.loads(data), session=session)

    @_create.register
    def _(data: list, session: Session = None):
        if not all(isinstance(i, dict) for i in data):
            raise ValueError("All items must be dicts")
        with get_session(session) as s:
            objs = [cls(**item) for item in data]
            s.add_all(objs)
            s.commit()
            for obj in objs:
                s.refresh(obj)
            log.success(f"[SCRUD] Bulk-created {len(objs)} {cls.__name__} records")
            return objs

    @classmethod
    def c(cls, data, session: Session = None):
        return _create(data, session=session)

    # --- READ ---
    @singledispatch
    def _read(data, session: Session = None):
        raise TypeError(f".r() unsupported type: {type(data)}")

    @_read.register
    def _(data: dict, session: Session = None):
        with get_session(session) as s:
            result = s.exec(select(cls).filter_by(**data)).first()
            log.debug(f"[SCRUD] Read by filter {data}: {result}")
            return result

    @_read.register
    def _(data: str, session: Session = None):
        with get_session(session) as s:
            result = s.exec(select(cls).where(cls.id == data)).first()
            log.debug(f"[SCRUD] Read by id {data}: {result}")
            return result

    @_read.register
    def _(data: uuid.UUID, session: Session = None):
        return _read(str(data), session=session)

    @_read.register
    def _(data: list, session: Session = None):
        if not data:
            return []
        with get_session(session) as s:
            if all(isinstance(i, dict) for i in data):
                return [_read(i, session=session) for i in data]
            if all(isinstance(i, (str, uuid.UUID)) for i in data):
                ids = [str(i) for i in data]
                result = s.exec(select(cls).where(cls.id.in_(ids))).all()
                log.debug(f"[SCRUD] Read by id list {ids}: {result}")
                return result
            raise TypeError("List must be all dicts or UUID/str")

    @classmethod
    def r(cls, data, session: Session = None):
        return _read(data, session=session)

    # --- UPDATE ---
    @classmethod
    def u(cls, match: dict, changes: dict, session: Session = None):
        obj = cls.r(match, session=session)
        with get_session(session) as s:
            for k, v in changes.items():
                setattr(obj, k, v)
            s.commit()
            s.refresh(obj)
            log.success(f"[SCRUD] Updated {cls.__name__} where {match} with {changes}")
            return obj

    # --- DELETE ---
    @classmethod
    def d(cls, data, session: Session = None):
        obj = cls.r(data, session=session)
        if obj:
            with get_session(session) as s:
                s.delete(obj)
                s.commit()
            log.warning(f"[SCRUD] Deleted {cls.__name__} with match {data}")
        else:
            log.warning(f"[SCRUD] Delete failed: {cls.__name__} not found for {data}")
        return obj

    # inject
    cls.c = c
    cls.r = r
    cls.u = u
    cls.d = d
    return cls
