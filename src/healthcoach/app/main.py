"""Сборка приложения."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.templating import Jinja2Templates

from healthcoach.app import routes_clients
from healthcoach.app.deps import Context, build_context

TEMPLATES_DIR = Path(__file__).parent / "templates"


def create_app(context: Context) -> FastAPI:
    """Собрать приложение поверх готового контекста."""
    app = FastAPI(title="Health Coaching")
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    app.include_router(routes_clients.build_router(context, templates))
    return app


def run() -> None:
    """Точка входа: uv run python -m healthcoach.app.main"""
    import uvicorn

    root = Path(__file__).resolve().parents[3]
    context = build_context(data_dir=root / "data", knowledge_dir=root / "knowledge")
    uvicorn.run(create_app(context), host="127.0.0.1", port=8765)


if __name__ == "__main__":
    run()
