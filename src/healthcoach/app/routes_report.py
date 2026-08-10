"""Запрос клиента, вычитка перед отправкой, сборка и утверждение черновика."""

from __future__ import annotations

from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from healthcoach.app.deps import Context, Repositories
from healthcoach.privacy.leak import LeakError
from healthcoach.privacy.redact import redact
from healthcoach.report.data import ReportError, collect_report
from healthcoach.report.draft import DraftError, generate_draft
from healthcoach.report.pdf import PdfBuildError, render_report_html, report_pdf
from healthcoach.report.scope import collect_inputs
from healthcoach.report.sections import SECTIONS
from healthcoach.scoring.findings import collect_findings
from healthcoach.scoring.references import Measurement, Subject


_in_flight: dict[int, int] = {}
"""Сколько разделов уже собрано у сборки, идущей прямо сейчас.

В базу разделы попадают все разом и только в самом конце, поэтому по ней
ход сборки не виден. Живёт в памяти одного процесса — этого хватает:
инструмент локальный, и работает с ним один человек.
"""


def build_router(context: Context, templates) -> APIRouter:
    router = APIRouter()

    def _snapshot_and_client(repo: Repositories, snapshot_id: int):
        snapshot = repo.snapshots.get(snapshot_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail=f"нет среза {snapshot_id}")
        client = repo.clients.get(snapshot.client_code)
        if client is None:
            raise HTTPException(
                status_code=404, detail=f"нет клиента {snapshot.client_code}"
            )
        return snapshot, client

    def _findings(repo: Repositories, snapshot, client):
        if not client.is_complete:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"карточка клиента {client.code} не заполнена: без пола и "
                    f"даты рождения целевой коридор не выбрать"
                ),
            )
        scoped = collect_inputs(repo, snapshot)
        measurements = [
            Measurement(
                m.analyte_id,
                m.value,
                m.units,
                label=m.raw_name,
                row_id=m.id,
                taken_on=m.taken_on,
                snapshot_id=m.snapshot_id,
            )
            for m in scoped.measurements
        ]
        subject_at = lambda d: Subject(sex=client.sex, age=client.age_on(d))  # noqa: E731
        subject = subject_at(snapshot.taken_on)
        return collect_findings(
            context.questionnaire,
            context.references,
            scoped.answers,
            measurements,
            subject,
            subject_at=subject_at,
        ), subject

    def _page(request: Request, repo: Repositories, snapshot, client):
        stored = repo.requests.get(snapshot.id)
        suggested = ""
        if stored is not None and not stored.redacted:
            suggested = redact(stored.raw, client).text
        titles = {section.id: section.title for section in SECTIONS}
        return templates.TemplateResponse(
            request,
            "report.html",
            {
                "snapshot": snapshot,
                "client": client,
                # Не "request": имя контекста, зарезервированное Starlette для
                # самого объекта Request; конфликт роняет TemplateResponse
                # при рендере — self.context["request"] перестаёт быть Request.
                "client_request": stored,
                "suggested": suggested,
                "sections": repo.drafts.sections(snapshot.id),
                "titles": titles,
                "approved_at": repo.drafts.approved_at(snapshot.id),
            },
        )

    @router.get("/snapshots/{snapshot_id}/draft", response_class=HTMLResponse)
    def draft_page(request: Request, snapshot_id: int):
        with context.session() as repo:
            snapshot, client = _snapshot_and_client(repo, snapshot_id)
            return _page(request, repo, snapshot, client)

    def _refuse_if_draft_is_frozen(repo: Repositories, snapshot_id: int) -> None:
        """Заморозка черновика распространяется и на запрос: иначе рядом с
        утверждёнными разделами оказался бы посторонний текст, а то, что
        реально ушло модели, было бы стёрто следующей правкой. Проверка
        только здесь, в маршруте — хранилище запроса ничего не знает про
        черновики, и это не место эту связь заводить."""
        if repo.drafts.approved_at(snapshot_id) is not None:
            raise HTTPException(
                status_code=409,
                detail="черновик утверждён — запрос клиента больше не меняется",
            )

    @router.post("/snapshots/{snapshot_id}/request")
    def save_request(snapshot_id: int, raw: str = Form(...)):
        with context.session() as repo:
            _snapshot_and_client(repo, snapshot_id)
            _refuse_if_draft_is_frozen(repo, snapshot_id)
            repo.requests.save(snapshot_id, raw)
        return RedirectResponse(f"/snapshots/{snapshot_id}/draft", status_code=303)

    @router.post("/snapshots/{snapshot_id}/request/redact")
    def save_redaction(snapshot_id: int, redacted: str = Form(...)):
        with context.session() as repo:
            _snapshot_and_client(repo, snapshot_id)
            _refuse_if_draft_is_frozen(repo, snapshot_id)
            if not repo.requests.set_redacted(snapshot_id, redacted):
                raise HTTPException(
                    status_code=400, detail="запрос клиента ещё не введён"
                )
        return RedirectResponse(f"/snapshots/{snapshot_id}/draft", status_code=303)

    @router.post("/snapshots/{snapshot_id}/request/approve")
    def approve_request(snapshot_id: int):
        with context.session() as repo:
            _snapshot_and_client(repo, snapshot_id)
            if not repo.requests.approve(snapshot_id):
                raise HTTPException(
                    status_code=400,
                    detail="вычитанного текста нет — утверждать нечего",
                )
        return RedirectResponse(f"/snapshots/{snapshot_id}/draft", status_code=303)

    @router.get("/snapshots/{snapshot_id}/draft/progress")
    def draft_progress(snapshot_id: int):
        """Сколько разделов уже собрано.

        Сборка идёт несколько минут: восемь обращений к модели подряд внутри
        одного запроса. Без этого экран коуча висит без единого признака
        жизни, и естественная реакция — нажать кнопку ещё раз, запустив
        вторую сборку.
        """
        with context.session() as repo:
            _snapshot_and_client(repo, snapshot_id)
            stored = len(repo.drafts.sections(snapshot_id))
        return {
            "собрано": _in_flight.get(snapshot_id, stored),
            "всего": len(SECTIONS),
        }

    @router.post("/snapshots/{snapshot_id}/draft")
    def build_draft(snapshot_id: int):
        with context.session() as repo:
            snapshot, client = _snapshot_and_client(repo, snapshot_id)
            stored = repo.requests.get(snapshot_id)
            if stored is None or not stored.approved:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "запрос клиента не вычитан и не утверждён — "
                        "до этого модели ничего не отправляется"
                    ),
                )
            if repo.drafts.approved_at(snapshot_id) is not None:
                raise HTTPException(
                    status_code=409, detail="черновик утверждён и не пересобирается"
                )
            findings, subject = _findings(repo, snapshot, client)
            request_text = stored.redacted

        if not findings:
            raise HTTPException(
                status_code=400,
                detail="находок нет — интерпретировать нечего",
            )

        _in_flight[snapshot_id] = 0
        try:
            generated = generate_draft(
                context.llm,
                findings,
                subject,
                request_text,
                context.specialists.public_view(),
                client,
                on_section=lambda done, total: _in_flight.__setitem__(
                    snapshot_id, done
                ),
            )
        except LeakError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except DraftError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        finally:
            _in_flight.pop(snapshot_id, None)

        try:
            with context.session() as repo:
                for section in generated:
                    repo.drafts.save_section(
                        snapshot_id,
                        section.section_id,
                        section.text,
                        section.finding_ids,
                    )
        except ValueError as exc:
            # Между проверкой approved_at выше и этой записью черновик мог
            # утвердить другой запрос — та же гонка, что и в edit_section.
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return RedirectResponse(f"/snapshots/{snapshot_id}/draft", status_code=303)

    @router.post("/snapshots/{snapshot_id}/draft/{section_row_id}/edit")
    def edit_section(snapshot_id: int, section_row_id: int, text: str = Form(...)):
        with context.session() as repo:
            _snapshot_and_client(repo, snapshot_id)
            if repo.drafts.approved_at(snapshot_id) is not None:
                raise HTTPException(
                    status_code=409,
                    detail="черновик утверждён — разделы больше не правятся",
                )
            try:
                found = repo.drafts.edit_section(section_row_id, snapshot_id, text)
            except ValueError as exc:
                # Утверждение могло случиться между проверкой строкой выше и
                # самой записью — это тоже 409, а не необработанный 500.
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            if not found:
                raise HTTPException(
                    status_code=404,
                    detail=f"в срезе {snapshot_id} нет раздела {section_row_id}",
                )
        return RedirectResponse(
            f"/snapshots/{snapshot_id}/draft#s{section_row_id}", status_code=303
        )

    @router.post("/snapshots/{snapshot_id}/draft/approve")
    def approve_draft(snapshot_id: int):
        with context.session() as repo:
            _snapshot_and_client(repo, snapshot_id)
            if repo.drafts.approved_at(snapshot_id) is not None:
                # DraftRepository.approve делает upsert: без этой проверки
                # повторное утверждение молча сдвинуло бы отметку времени —
                # это данные аудита, а не то, что можно переписать задним
                # числом.
                raise HTTPException(
                    status_code=409, detail="черновик уже утверждён"
                )
            if not repo.drafts.approve(
                snapshot_id, datetime.now(), context.questionnaire.version
            ):
                raise HTTPException(
                    status_code=400, detail="черновика нет — утверждать нечего"
                )
        return RedirectResponse(f"/snapshots/{snapshot_id}/draft", status_code=303)

    @router.get("/snapshots/{snapshot_id}/report.pdf")
    def report_file(snapshot_id: int):
        with context.session() as repo:
            snapshot, client = _snapshot_and_client(repo, snapshot_id)
            # Незаполненная карточка (только у строк со схемы версии 1) —
            # некорректный запрос про клиента, а не конфликт с состоянием
            # черновика: тот же 400, что и при сборке черновика в
            # build_draft/_findings выше. Проверка здесь, до collect_report,
            # оставляет 409 этого маршрута означать ровно одно — черновик не
            # утверждён, — а не смешивать с этим случаем.
            if not client.is_complete:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"карточка клиента {client.code} не заполнена: без пола и "
                        f"даты рождения целевой коридор не выбрать"
                    ),
                )
            try:
                data = collect_report(
                    repo,
                    context.questionnaire,
                    context.references,
                    context.coach,
                    snapshot_id,
                )
            except ReportError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc

        try:
            body = report_pdf(render_report_html(data, templates))
        except PdfBuildError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        name = f"отчёт-{data.client_code}-{data.taken_on.isoformat()}.pdf"
        # Заголовок HTTP — latin-1: кириллица в filename= его ломает, поэтому
        # настоящее имя уходит только в filename* (RFC 5987), а filename=
        # несёт ASCII-запасной вариант для клиентов, которые filename* не
        # читают.
        fallback = f"report-{data.client_code}-{data.taken_on.isoformat()}.pdf"
        disposition = (
            f'attachment; filename="{fallback}"; '
            f"filename*=UTF-8''{quote(name)}"
        )
        return Response(
            content=body,
            media_type="application/pdf",
            headers={"content-disposition": disposition},
        )

    return router
