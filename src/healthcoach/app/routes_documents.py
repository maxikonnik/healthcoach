"""Загрузка выгрузки лаборатории к срезу."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import RedirectResponse

from healthcoach.app.deps import Context
from healthcoach.intake.documents import DocumentError, read_document
from healthcoach.intake.lab_table import LabTableError, parse_number
from healthcoach.intake.measurements import prepare_measurements

def build_router(context: Context) -> APIRouter:
    router = APIRouter()

    @router.post("/snapshots/{snapshot_id}/documents")
    async def upload_document(snapshot_id: int, file: UploadFile = File(...)):
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
        except (DocumentError, LabTableError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        with context.session() as repo:
            for prepared in prepare_measurements(context.references, read.table):
                repo.snapshots.add_measurement(
                    snapshot_id,
                    analyte_id=prepared.analyte_id,
                    raw_name=prepared.raw_name,
                    value=prepared.value,
                    raw_value=prepared.raw_value,
                    units=prepared.units,
                    taken_on=snapshot.taken_on,
                    source=read.source,
                    document_id=document.id,
                )

        return RedirectResponse(f"/snapshots/{snapshot_id}", status_code=303)

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
