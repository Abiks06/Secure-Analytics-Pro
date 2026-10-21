from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import auth, datasets, system
from app.core.config import get_keys, get_settings
from app.core.middleware import SecurityHeadersMiddleware
from app.db.session import engine, init_db
from app.services import jobs

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("sap")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    get_keys()  # fail fast on missing/invalid key material
    await init_db()
    await jobs.recover_interrupted()
    yield
    await engine.dispose()


settings = get_settings()
app = FastAPI(
    title="Secure Analytics Pro API",
    version="2.0.0",
    lifespan=lifespan,
    docs_url=None if settings.is_prod else "/api/docs",
    redoc_url=None,
    openapi_url=None if settings.is_prod else "/api/openapi.json",
)

app.add_middleware(GZipMiddleware, minimum_size=2048)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
    max_age=600,
)
app.add_middleware(SecurityHeadersMiddleware, hsts=settings.is_prod, connect_src=settings.supabase_url or "")


@app.exception_handler(RequestValidationError)
async def _validation(_request: Request, exc: RequestValidationError) -> JSONResponse:
    first = exc.errors()[0] if exc.errors() else {}
    field = ".".join(str(p) for p in first.get("loc", [])[1:])
    msg = str(first.get("msg", "Invalid request")).removeprefix("Value error, ")
    return JSONResponse({"detail": f"{field}: {msg}" if field else msg}, status_code=422)


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse({"detail": "Internal server error"}, status_code=500)


app.include_router(auth.router)
app.include_router(datasets.router)
app.include_router(system.router)

# Production: serve the built frontend from the same origin (no CORS, strict cookies just work).
static_dir: Path | None = settings.static_dir
if static_dir and static_dir.exists():
    app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, detail="Not found")
        candidate = (static_dir / path).resolve()
        if path and candidate.is_file() and static_dir.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(static_dir / "index.html")
