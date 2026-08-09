"""Экран среза: ответы анкеты, ввод показателей, находки."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse

from healthcoach.app.deps import Context, Repositories
from healthcoach.intake.answers import AnswersError, ImportedAnswers, parse_answers
from healthcoach.intake.resolve import resolve_analyte
from healthcoach.knowledge.sex import SexError
from healthcoach.knowledge.units import UnitError, convert_to_reference
from healthcoach.scoring.findings import collect_findings
from healthcoach.scoring.references import Measurement, Subject
from healthcoach.storage.snapshots import StoredMeasurement

UNRESOLVED = ""
"""analyte_id нераспознанного показателя: он хранится, но не трактуется."""


@dataclass(frozen=True)
class Row:
    measurement: StoredMeasurement
    title: str
    problem: str | None


@dataclass(frozen=True)
class DocumentImport:
    """Итог загрузки документа, показываемый один раз — сразу после неё.

    `unparsed` — строки, которые разбор не смог превратить в запись бланка
    вовсе (не «показатель не распознан», а «этого не понять как строку
    таблицы»). Они не становятся измерением ни в каком виде и существуют
    только здесь, чтобы коуч ввёл их руками.
    """

    filename: str
    source: str
    count: int
    unparsed: tuple[str, ...]


def _rows(context: Context, repo: Repositories, snapshot_id: int) -> list[Row]:
    rows: list[Row] = []
    for measurement in repo.snapshots.measurements(snapshot_id):
        if not measurement.analyte_id:
            resolution = resolve_analyte(context.references, measurement.raw_name)
            problem = "показатель не распознан"
            if resolution.is_ambiguous:
                candidates = ", ".join(a.name for a in resolution.candidates)
                problem = f"название подходит нескольким показателям: {candidates}"
            rows.append(Row(measurement, measurement.raw_name, problem))
            continue
        analyte = context.references.analyte(measurement.analyte_id)
        if analyte is None:
            rows.append(
                Row(measurement, measurement.analyte_id, "показатель не распознан")
            )
            continue
        problem = None
        if measurement.units.strip().casefold() != analyte.units.strip().casefold():
            problem = f"единицы не сопоставлены: {measurement.units}"
        rows.append(Row(measurement, analyte.name, problem))
    return rows


def render_snapshot_page(
    request: Request,
    templates,
    context: Context,
    repo: Repositories,
    snapshot,
    *,
    imported: ImportedAnswers | None = None,
    document_import: DocumentImport | None = None,
):
    """Отрисовать экран среза. Общая точка входа: и обычный показ страницы,
    и оба обработчика загрузки (анкеты, документа) рендерят её напрямую —
    редирект не пережил бы то, что нужно показать один раз."""
    return templates.TemplateResponse(
        request,
        "snapshot.html",
        {
            "snapshot": snapshot,
            "rows": _rows(context, repo, snapshot.id),
            "answers_count": len(repo.snapshots.answers(snapshot.id)),
            "imported": imported,
            "document_import": document_import,
        },
    )


def build_router(context: Context, templates) -> APIRouter:
    router = APIRouter()

    def _snapshot_or_404(repo: Repositories, snapshot_id: int):
        snapshot = repo.snapshots.get(snapshot_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail=f"нет среза {snapshot_id}")
        return snapshot

    def _page(
        request: Request,
        repo: Repositories,
        snapshot,
        imported: ImportedAnswers | None = None,
    ):
        return render_snapshot_page(
            request, templates, context, repo, snapshot, imported=imported
        )

    @router.get("/snapshots/{snapshot_id}", response_class=HTMLResponse)
    def snapshot_page(request: Request, snapshot_id: int):
        with context.session() as repo:
            snapshot = _snapshot_or_404(repo, snapshot_id)
            return _page(request, repo, snapshot)

    @router.post("/snapshots/{snapshot_id}/answers", response_class=HTMLResponse)
    async def upload_answers(
        request: Request, snapshot_id: int, file: UploadFile = File(...)
    ):
        with context.session() as repo:
            snapshot = _snapshot_or_404(repo, snapshot_id)

        payload = await file.read()
        try:
            imported = parse_answers(context.questionnaire, payload)
        except AnswersError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        # Код клиента лежит в самом файле. Не сверить его — значит позволить
        # анкете одного человека определить рекомендации другому: в папке
        # загрузок у коуча лежат файлы всех клиентов, и различаются они
        # только именем.
        if imported.client_code != snapshot.client_code:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"файл заполнен клиентом {imported.client_code!r}, "
                    f"а срез принадлежит {snapshot.client_code!r}"
                ),
            )

        with context.session() as repo:
            repo.snapshots.save_answers(snapshot_id, imported.answers)
            return _page(request, repo, snapshot, imported=imported)

    @router.post("/snapshots/{snapshot_id}/measurements")
    def add_measurement(
        snapshot_id: int,
        raw_name: str = Form(...),
        value: str = Form(...),
        units: str = Form(...),
        taken_on: str = Form(...),
    ):
        try:
            number = float(value.replace(",", "."))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="значение должно быть числом") from exc
        try:
            when = date.fromisoformat(taken_on)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="дата в формате ГГГГ-ММ-ДД") from exc

        resolution = resolve_analyte(context.references, raw_name)
        analyte_id, stored_value, stored_units = UNRESOLVED, number, units
        if resolution.is_certain:
            analyte_id = resolution.analyte.id
            try:
                stored_value = convert_to_reference(resolution.analyte, number, units)
                stored_units = resolution.analyte.units
            except UnitError:
                stored_value, stored_units = number, units

        with context.session() as repo:
            _snapshot_or_404(repo, snapshot_id)
            repo.snapshots.add_measurement(
                snapshot_id,
                analyte_id=analyte_id,
                raw_name=raw_name,
                value=stored_value,
                raw_value=value.strip(),
                units=stored_units,
                taken_on=when,
            )
        return RedirectResponse(f"/snapshots/{snapshot_id}", status_code=303)

    @router.post("/snapshots/{snapshot_id}/measurements/{measurement_id}/confirm")
    def confirm(snapshot_id: int, measurement_id: int):
        with context.session() as repo:
            _snapshot_or_404(repo, snapshot_id)
            if not repo.snapshots.confirm_measurement(measurement_id, snapshot_id):
                raise HTTPException(
                    status_code=404,
                    detail=f"в срезе {snapshot_id} нет показателя {measurement_id}",
                )
        return RedirectResponse(f"/snapshots/{snapshot_id}", status_code=303)

    @router.get("/snapshots/{snapshot_id}/findings", response_class=PlainTextResponse)
    def findings(snapshot_id: int):
        """Находки текстом: полноценный отчёт собирает план 4.

        Пол и возраст берутся из карточки клиента и нигде не подставляются
        по умолчанию: почти каждый целевой коридор задан для пола и
        возрастного диапазона, и подстановка молча считала бы находки для
        другого человека. Возраст — на дату среза, а не на сегодня.
        """
        with context.session() as repo:
            snapshot = _snapshot_or_404(repo, snapshot_id)
            client = repo.clients.get(snapshot.client_code)
            if client is None:
                raise HTTPException(
                    status_code=404, detail=f"нет клиента {snapshot.client_code}"
                )
            measurements = [
                Measurement(m.analyte_id, m.value, m.units, label=m.raw_name)
                for m in repo.snapshots.measurements(snapshot_id)
                if m.confirmed
            ]
            answers = repo.snapshots.answers(snapshot_id)

        if not client.is_complete:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"карточка клиента {client.code} не заполнена: без пола и "
                    f"даты рождения целевой коридор не выбрать"
                ),
            )

        age = client.age_on(snapshot.taken_on)
        try:
            subject = Subject(sex=client.sex, age=age)
        except SexError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"в карточке клиента {client.code} неверный пол: {exc}",
            ) from exc

        found = collect_findings(
            context.questionnaire,
            context.references,
            answers,
            measurements,
            subject,
        )
        lines = [
            f"Срез {snapshot.taken_on}, клиент {snapshot.client_code}",
            f"Считано для: пол {subject.sex}, возраст {age} на дату среза",
            "",
        ]
        for finding in found:
            value = "—" if finding.value is None else finding.value
            partial = (
                f" [заполнено {finding.answered} из {finding.total}]"
                if finding.partial
                else ""
            )
            lines.append(
                f"[{finding.kind}] {finding.title}: {value} {finding.units} "
                f"— {finding.status}{partial}"
                + (f" ({finding.note})" if finding.note else "")
            )
        return "\n".join(lines)

    return router
