import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from . import models  # noqa: F401  (register tables)
from .config import settings
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


# The Flutter web build, served from the same origin as the API (no CORS needed).
# Anything that isn't /api, /docs or a real file gets index.html so app routes work on reload.
if settings.web_dir and Path(settings.web_dir, "index.html").is_file():
    web_root = Path(settings.web_dir).resolve()

    @app.get("/{path:path}", include_in_schema=False)
    def web_app(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "Not found")
        target = (web_root / path).resolve()
        if path and target.is_file() and web_root in target.parents:
            # hashed assets can be cached; index.html and the service worker must not be
            cache = "no-cache" if target.name in ("index.html", "flutter_service_worker.js", "version.json") \
                else "public, max-age=604800"
            return FileResponse(target, headers={"Cache-Control": cache})
        return FileResponse(web_root / "index.html", headers={"Cache-Control": "no-cache"})
