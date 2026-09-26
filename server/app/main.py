import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import models  # noqa: F401  (register tables)
from .db import Base, engine
from .routers import auth, households, products, shopping, stock

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # v0.x: create missing tables on start. Switch to Alembic migrations before the
    # first change to an existing table.
    Base.metadata.create_all(engine)
    yield


app = FastAPI(title="Kasita", version="0.1.0", lifespan=lifespan,
              description="Household pantry, shopping list, barcode and receipt scanning.")

for r in (auth.router, households.router, products.router, stock.router, shopping.router):
    app.include_router(r)


@app.get("/api/health", tags=["meta"])
def health():
    return {"status": "ok", "version": app.version}
