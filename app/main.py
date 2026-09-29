"""FastAPI app: routes + error handling. Every error leaves as JSON with a 4xx code."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.ai.ollama import OllamaClient
from app.api import costs, images, jobs, posts
from app.api.deps import DB
from app.config import get_settings
from app.errors import AppError
from app.logging_setup import setup_logging

log = logging.getLogger("app")


def error_body(code: str, message: str, details: object | None = None) -> dict:
    body: dict = {"error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    return body


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_level)
    app = FastAPI(
        title="AI Image Understanding & Content Matching Engine",
        version="1.0.0",
        description="Tags images with a local vision model, matches them to posts, and refuses bad matches.",
    )

    @app.exception_handler(AppError)
    async def app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=error_body(exc.code, exc.message))

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"loc": list(e.get("loc", [])), "msg": e.get("msg", ""), "type": e.get("type", "")}
            for e in exc.errors()
        ]
        return JSONResponse(status_code=422, content=error_body("validation_error", "invalid request", details))

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=error_body("http_error", str(exc.detail)))

    @app.exception_handler(IntegrityError)
    async def integrity_error(_: Request, exc: IntegrityError) -> JSONResponse:
        log.warning("integrity error: %s", exc.orig)
        return JSONResponse(status_code=409, content=error_body("conflict", "the request conflicts with existing data"))

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception) -> JSONResponse:
        # last resort; tests assert no route gets here for bad input
        log.exception("unhandled error")
        return JSONResponse(status_code=500, content=error_body("internal_error", "internal server error"))

    @app.get("/health", tags=["health"])
    def health(db: DB) -> dict:
        db.execute(text("SELECT 1"))
        ollama_ok = OllamaClient(settings.ollama_base_url, 3).ping()
        return {
            "status": "ok",
            "database": "ok",
            "ollama": "ok" if ollama_ok else "unreachable",
            "vision_model": settings.vision_model,
            "embed_model": settings.embed_model,
        }

    app.include_router(images.router)
    app.include_router(jobs.router)
    app.include_router(posts.router)
    app.include_router(costs.router)
    return app


app = create_app()
