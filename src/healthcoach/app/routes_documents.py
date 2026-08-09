"""Загрузка выгрузки лаборатории к срезу."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from healthcoach.app.deps import Context
from healthcoach.app.routes_snapshots import DocumentImport, render_snapshot_page
from healthcoach.intake.documents import DocumentError, read_document
from healthcoach.intake.lab_table import parse_number
from healthcoach.intake.measurements import prepare_measurements


def build_router(context: Context, templates) -> APIRouter:
    router = APIRouter()

    @router.post("/snapshots/{snapshot_id}/documents", response_class=HTMLResponse)
    async def upload_document(
        request: Request, snapshot_id: int, file: UploadFile = File(...)
    ):
        with context.session() as repo:
            snapshot = repo.snapshots.get(snapshot_id)
            if snapshot is None:
                raise HTTPException(
                    status_code=404, detail=f"нет среза {snapshot_id}"
                )

        payload = await file.read()
        suffix = Path(file.filename or "").suffix.casefold()
        folder = context.documents_dir / str(snapshot_id)
        folder.mkdir(parents=True, exist_ok=True)

        added_at = datetime.now()
        with context.session() as repo:
            document = repo.documents.add(
                snapshot_id, file.filename or "без имени", "", added_at
            )

        stored_path = folder / f"{document.id}{suffix}"
        stored_path.write_bytes(payload)

        try:
            read = read_document(stored_path, context.ocr)
        except DocumentError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        prepared = prepare_measurements(context.references, read.table)
        with context.session() as repo:
            for item in prepared:
                repo.snapshots.add_measurement(
                    snapshot_id,
                    analyte_id=item.analyte_id,
                    raw_name=item.raw_name,
                    value=item.value,
                    raw_value=item.raw_value,
                    units=item.units,
                    taken_on=snapshot.taken_on,
                    source=read.source,
                    document_id=document.id,
                )

        # Редирект на /snapshots/{id} не пережил бы то, что нужно показать
        # один раз: сколько показателей вошло и какие строки разбор не
        # понял вовсе. Страница рендерится напрямую — тем же приёмом, что
        # и загрузка анкеты в routes_snapshots.py.
        with context.session() as repo:
            snapshot = repo.snapshots.get(snapshot_id)
            return render_snapshot_page(
                request,
                templates,
                context,
                repo,
                snapshot,
                document_import=DocumentImport(
                    filename=document.filename,
                    source=read.source,
                    count=len(prepared),
                    unparsed=read.table.unparsed,
                ),
            )

    @router.post("/snapshots/{snapshot_id}/measurements/{measurement_id}/value")
    def set_value(snapshot_id: int, measurement_id: int, value: str = Form(...)):
        number = parse_number(value)
        if number is None:
            raise HTTPException(
                status_code=400, detail="значение должно быть числом"
            )
        with context.session() as repo:
            if repo.snapshots.get(snapshot_id) is None:
                raise HTTPException(
                    status_code=404, detail=f"нет среза {snapshot_id}"
                )
            if not repo.snapshots.set_value(measurement_id, snapshot_id, number):
                raise HTTPException(
                    status_code=404,
                    detail=f"в срезе {snapshot_id} нет показателя {measurement_id}",
                )
        return RedirectResponse(f"/snapshots/{snapshot_id}", status_code=303)

    return router
