import importlib.util
import logging
import re
import types
from contextlib import contextmanager
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from loguru import logger as log
from sqlalchemy import MetaData, Engine, create_engine
from sqlmodel import SQLModel, Session

def sanitize(text: str) -> str:
    text = str(text).strip()
    text = re.sub(r"[^\w]", "_", text)
    if text[0].isdigit():
        text = "_" + text
    return text.lower()

@dataclass
class Database:
    path: Path
    model_path: Path = None #for generating models from a .py file
    input_model: SQLModel | list[SQLModel] = None #for generating models from an SQL Model / List of SQL Models
    manager = None

    def __post_init__(self):
        if not self.dir.exists(): raise FileNotFoundError
        if not hasattr(self, "from_project_bool"):
            self.path: Path = self.dir / f"{self.name}.db"
            self.input_dir: Path = self.dir / f"{self.name}-db-inputs"
            self.model_path: Path = self.dir / f"{self.name}-db-models.py"
        self.path.touch(exist_ok=True)
        self.input_dir.mkdir(exist_ok=True)
        self.model_path.touch(exist_ok=True)
        setattr(self, "manager", DatabaseManager(self))

class DatabaseManager:
    def __init__(self, db: Database):
        self.db = db
        self.project = self.db.project
        _ = self.engine, self.models
        self.migrate()
        #_ = self.xlsx_inputs
        log.success(f"{self}: Successfully Initialized!")

    def __repr__(self):
        return f"[{self.db.name.title()}.DatabaseManager]"

    class InterceptHandler(logging.Handler):
        def __init__(self, db_repr: str):
            super().__init__()
            self.db_repr = db_repr

        def emit(self, record):
            msg = f"{self.db_repr} [{record.levelname}] {record.getMessage()}"
            if record.levelno >= logging.ERROR:
                log.opt(depth=6, exception=record.exc_info).error(msg)
            elif record.levelno >= logging.WARNING:
                log.warning(msg)
            elif record.levelno >= logging.INFO:
                log.debug(msg)
            else:
                log.debug(msg)

    @cached_property
    def engine(self) -> Engine:
        logger = logging.getLogger("sqlalchemy.engine")
        if not any(isinstance(h, self.InterceptHandler) for h in logger.handlers):
            logger.handlers = [self.InterceptHandler(repr(self))]
            logger.setLevel(logging.DEBUG)
        return create_engine(
            f"sqlite:///{self.db.path}",
            future=True,
            echo=False
        )

    @contextmanager
    def session(self):
        session = Session(self.engine)
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @cached_property
    def models(self) -> types.SimpleNamespace:
        from back_end.database.scrud import scrud

        model_map = {}

        # from model_path
        if self.db.model_path.exists():
            spec = importlib.util.spec_from_file_location("models", self.db.model_path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            file_models = {
                name.lower(): scrud(self, obj)
                for name, obj in vars(mod).items()
                if isinstance(obj, type)
                and issubclass(obj, SQLModel)
                and getattr(obj, "__tablename__", None)
            }

            log.debug(f"{self}: Loaded {len(file_models)} models from file")
            model_map.update(file_models)

        # from input_model (list or single)
        input_models = self.db.input_model
        if input_models:
            if not isinstance(input_models, list):
                input_models = [input_models]

            direct_models = {
                model.__name__.lower(): scrud(self, model)
                for model in input_models
                if isinstance(model, type)
                and issubclass(model, SQLModel)
                and getattr(model, "__tablename__", None)
            }

            log.debug(f"{self}: Loaded {len(direct_models)} models from input")
            model_map.update(direct_models)

        if not model_map:
            log.warning(f"{self}: No models found from path or input!")

        log.info(f"{self}: Accessible Namespaces:\n" + "\n".join(f" - {k}" for k in model_map))

        return types.SimpleNamespace(**model_map)


    def migrate(self):
        tables = [
            obj.__table__
            for obj in self.models.__dict__.values()
            if hasattr(obj, "__table__")
        ]
        if not tables:
            log.warning(f"{self}: No models found to migrate.")
            return

        meta = MetaData()
        for t in tables:
            t.to_metadata(meta)        # clone into the new metadata

        meta.create_all(self.engine, checkfirst=True)
        log.success(f"{self}: Migrated {len(tables)} model(s) ✔")

    ##ignore this shit here this is wip
    @cached_property
    def xlsx_inputs(self):
        files = []
        for file in self.meta.input_dir.glob("*.xlsx"):
            table = sanitize(file.stem.lower())
            try:
                DatabaseManager.xlsx_to_sqlite(self.meta.db_path, table, file)
                log.debug(f"[DB Manager] Wrote {file.name} to {table}")
                files.append(file.name)
            except Exception as e:
                log.error(f"[DB Manager] Failed on {file.name}: {e}")
        return files

    @staticmethod
    def xlsx_to_sqlite(db_path: Path, table: str, file: Path):
        import uuid
        import pandas as pd
        from datetime import datetime
        import sqlite3

        df = pd.read_excel(file).where(pd.notnull, None)
        df.columns = [sanitize(c) for c in df.columns]
        df.insert(0, "uuid", [str(uuid.uuid4()) for _ in df.index])
        df.insert(1, "migration_date", datetime.utcnow().isoformat())
        table = sanitize(table)

        with sqlite3.connect(str(db_path)) as conn:
            cur = conn.cursor()

            # Ensure table exists with base columns
            cur.execute(f'''
                CREATE TABLE IF NOT EXISTS "{table}" (
                    uuid TEXT PRIMARY KEY,
                    migrated_at TEXT
                )
            ''')

            # Check existing columns
            cur.execute(f'PRAGMA table_info("{table}")')
            existing_cols = {row[1] for row in cur.fetchall()}

            # Add missing columns
            for col in df.columns:
                if col not in existing_cols:
                    cur.execute(f'ALTER TABLE "{table}" ADD COLUMN "{col}" TEXT')

            # Batch insert
            cols = ', '.join(f'"{c}"' for c in df.columns)
            placeholders = ', '.join(['?'] * len(df.columns))
            insert_sql = f'INSERT INTO "{table}" ({cols}) VALUES ({placeholders})'
            cur.executemany(insert_sql, df.itertuples(index=False, name=None))

            conn.commit()

