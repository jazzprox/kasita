"""Bring the database schema up to date with Alembic (runs on startup).

Databases created before migrations existed (v0.1 used create_all) already
match revision 0001, so they are stamped with it instead of re-created.
"""
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from .db import engine

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"


def alembic_config() -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    return cfg


def migrate() -> None:
    cfg = alembic_config()
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        tables = set(inspect(conn).get_table_names())
        if "alembic_version" not in tables and "users" in tables:
            command.stamp(cfg, "0001")
        command.upgrade(cfg, "head")
