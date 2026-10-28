"""Сборка приложения."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.templating import Jinja2Templates

from healthcoach.app import (
    routes_clients,
    routes_documents,
    routes_report,
    routes_snapshots,
)
from healthcoach.app.deps import Context, build_context

TEMPLATES_DIR = Path(__file__).parent / "templates"


def create_app(context: Context) -> FastAPI:
    """Собрать приложение поверх готового контекста."""
    app = FastAPI(title="Health Coaching")
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    app.include_router(routes_clients.build_router(context, templates))
    app.include_router(routes_snapshots.build_router(context, templates))
    app.include_router(routes_documents.build_router(context, templates))
    app.include_router(routes_report.build_router(context, templates))
    return app


HOST = "127.0.0.1"
PORT = 8765
URL = f"http://{HOST}:{PORT}"
"""Адрес инструмента. Здесь, а не по месту вызова: его знают два входа —
терминальный и оконный (`healthcoach.app.desktop`), — и разойтись им
нельзя."""


def default_app():
    """Приложение поверх рабочих папок проекта.

    Данные и база знаний лежат рядом с исходниками, а не там, откуда
    запустили: инструмент локальный, и папка `data/` у него одна.
    """
    root = Path(__file__).resolve().parents[3]
    context = build_context(data_dir=root / "data", knowledge_dir=root / "knowledge")
    return create_app(context)


def run() -> None:
    """Точка входа: uv run python -m healthcoach.app.main"""
    import uvicorn

    uvicorn.run(default_app(), host=HOST, port=PORT)


if __name__ == "__main__":
    run()
