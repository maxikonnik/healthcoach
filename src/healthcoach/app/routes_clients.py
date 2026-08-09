"""Список клиентов, карточка клиента, выдача опросника."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from healthcoach.app.deps import Context
from healthcoach.intake.questionnaire_html import (
    QuestionnaireHtmlError,
    render_questionnaire,
)


def build_router(context: Context, templates) -> APIRouter:
    router = APIRouter()

    @router.get("/", response_class=HTMLResponse)
    def clients_page(request: Request):
        with context.session() as repo:
            return templates.TemplateResponse(
                request, "clients.html", {"clients": repo.clients.all()}
            )

    @router.post("/clients")
    def add_client(full_name: str = Form(...), contacts: str = Form("")):
        with context.session() as repo:
            try:
                client = repo.clients.add(full_name, contacts=contacts or None)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        return RedirectResponse(f"/clients/{client.code}", status_code=303)

    @router.get("/clients/{code}", response_class=HTMLResponse)
    def client_page(request: Request, code: str):
        with context.session() as repo:
            client = repo.clients.get(code)
            if client is None:
                raise HTTPException(status_code=404, detail=f"нет клиента {code}")
            return templates.TemplateResponse(
                request,
                "client.html",
                {
                    "client": client,
                    "snapshots": repo.snapshots.for_client(code),
                    "extra_blocks": [
                        b for b in context.questionnaire.blocks if not b.core
                    ],
                },
            )

    @router.post("/clients/{code}/snapshots")
    def add_snapshot(code: str, taken_on: str = Form(...), note: str = Form("")):
        try:
            when = date.fromisoformat(taken_on)
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail="дата в формате ГГГГ-ММ-ДД"
            ) from exc
        with context.session() as repo:
            if repo.clients.get(code) is None:
                raise HTTPException(status_code=404, detail=f"нет клиента {code}")
            repo.snapshots.create(code, when, note=note or None)
        return RedirectResponse(f"/clients/{code}", status_code=303)

    @router.get("/clients/{code}/questionnaire")
    def questionnaire_file(code: str, extra: list[str] = Query(default=())):
        with context.session() as repo:
            if repo.clients.get(code) is None:
                raise HTTPException(status_code=404, detail=f"нет клиента {code}")
        try:
            html = render_questionnaire(
                context.questionnaire, code, extra_block_ids=extra
            )
        except QuestionnaireHtmlError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return HTMLResponse(
            html,
            headers={
                "content-disposition": (
                    f'attachment; filename="questionnaire-{code}.html"'
                )
            },
        )

    return router
