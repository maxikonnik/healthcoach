"""Список клиентов, карточка клиента, выдача опросника."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from healthcoach.app.deps import Context
from healthcoach.app.status import client_overview
from healthcoach.knowledge.sex import SexError
from healthcoach.intake.questionnaire_html import (
    QuestionnaireHtmlError,
    render_questionnaire,
)


def _birth_date(raw: str) -> date:
    try:
        born = date.fromisoformat(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail="дата рождения в формате ГГГГ-ММ-ДД"
        ) from exc
    if born > date.today():
        raise HTTPException(
            status_code=400, detail=f"дата рождения {born} в будущем"
        )
    return born


def build_router(context: Context, templates) -> APIRouter:
    router = APIRouter()

    @router.get("/", response_class=HTMLResponse)
    def clients_page(request: Request):
        with context.session() as repo:
            rows = [
                (client, client_overview(repo, client))
                for client in repo.clients.all()
            ]
            rows.sort(
                key=lambda pair: (
                    pair[1].latest_taken_on is None,
                    -pair[1].latest_taken_on.toordinal()
                    if pair[1].latest_taken_on
                    else 0,
                )
            )
            return templates.TemplateResponse(
                request, "clients.html", {"rows": rows}
            )

    @router.post("/clients")
    def add_client(
        full_name: str = Form(...),
        sex: str = Form(...),
        birth_date: str = Form(...),
        contacts: str = Form(""),
    ):
        born = _birth_date(birth_date)
        with context.session() as repo:
            try:
                client = repo.clients.add(
                    full_name, sex, born, contacts=contacts or None
                )
            except (ValueError, SexError) as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        return RedirectResponse(f"/clients/{client.code}", status_code=303)

    @router.post("/clients/{code}")
    def update_client(
        code: str,
        sex: str = Form(...),
        birth_date: str = Form(...),
        contacts: str = Form(""),
        note: str = Form(""),
    ):
        """Дозаполнить карточку.

        Нужна не только для правки: карточки, заведённые до появления пола
        и даты рождения, остаются без них после перехода схемы, и без этой
        формы заполнить их было бы негде.
        """
        born = _birth_date(birth_date)
        with context.session() as repo:
            try:
                updated = repo.clients.update(
                    code, sex, born, contacts=contacts or None, note=note or None
                )
            except SexError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            if not updated:
                raise HTTPException(status_code=404, detail=f"нет клиента {code}")
        return RedirectResponse(f"/clients/{code}", status_code=303)

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
