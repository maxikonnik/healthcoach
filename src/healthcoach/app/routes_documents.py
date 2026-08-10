"""Загрузка выгрузки лаборатории к срезу."""

from __future__ import annotations

from contextlib import suppress
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from healthcoach.app.deps import Context
from healthcoach.app.routes_snapshots import DocumentImport, render_snapshot_page
from healthcoach.intake.documents import DocumentError, read_document
from healthcoach.intake.lab_table import parse_number
from healthcoach.intake.measurements import prepare_measurements
from healthcoach.privacy.redact import name_stems
from healthcoach.storage.clients import Client

HEADER_LINES = 3
"""Сколько первых строк документа показывать коучу как шапку — печатные
бланки кладут ФИО и дату в начало, до самой таблицы показателей."""


def document_belongs_to(client: Client, lines: tuple[str, ...] | list[str]) -> bool:
    """Нашлась ли в тексте документа хоть одна основа имени клиента.

    Основы берутся `name_stems` из `healthcoach.privacy.redact` — тем же
    правилом склонения, что и у сторожа обезличивания, а не второй копией:
    расхождение двух копий одного правила уже было находкой финального
    ревью плана 3. `name_stems` не обещает, что первый элемент — фамилия:
    у клиента с фамилией короче четырёх букв («Ким Мария Сергеевна») она
    вовсе выпадает из списка, и первым элементом становится имя. Список —
    просто набор того, что мы знаем об имени этого клиента, без порядка и
    без выделенной «главной» основы, поэтому предполагать позицию нельзя.

    Предупреждение — только если НИ ОДНА основа не нашлась; хватает любой
    одной. Сравнение регистронезависимое: распознавание бланка не
    сохраняет регистр надёжно, а результат — предупреждение, не отказ, так
    что ложное совпадение не страшнее пропуска.
    """
    stems = name_stems(client)
    if not stems:
        return True
    text = "\n".join(lines).casefold()
    return any(stem.casefold() in text for stem in stems)


def build_router(context: Context, templates) -> APIRouter:
    router = APIRouter()

    @router.post("/snapshots/{snapshot_id}/documents", response_class=HTMLResponse)
    def upload_document(
        request: Request, snapshot_id: int, file: UploadFile = File(...)
    ):
        # Синхронный def: чтение файла, обращения к sqlite и распознавание
        # фотографии — блокирующая работа. FastAPI выполняет такой
        # обработчик в пуле потоков; будь он async def, вся эта работа шла
        # бы прямо на цикле событий, и сервер не отвечал бы никому на время
        # разбора одной фотографии.
        with context.session() as repo:
            snapshot = repo.snapshots.get(snapshot_id)
            if snapshot is None:
                raise HTTPException(
                    status_code=404, detail=f"нет среза {snapshot_id}"
                )

        payload = file.file.read()
        suffix = Path(file.filename or "").suffix.casefold()
        folder = context.documents_dir / str(snapshot_id)
        folder.mkdir(parents=True, exist_ok=True)

        # Файл сперва пишется во временное имя и читается им же: запись в
        # базу и постоянное, названное идентификатором документа имя на
        # диске появляются только после того, как read_document подтвердит,
        # что документ вообще пригоден. Иначе неудачная загрузка (плохой
        # PDF, чужой формат, битое фото) оставляла бы висячую строку в
        # documents и файл на диске, которые коуч не может ни увидеть, ни
        # удалить.
        staging_path = folder / f".upload-{uuid4().hex}{suffix}"
        staging_path.write_bytes(payload)

        try:
            read = read_document(staging_path, context.ocr)
        except DocumentError as exc:
            _discard_staging(staging_path, folder)
            raise HTTPException(
                status_code=400, detail=_coach_facing(exc, staging_path, file)
            ) from exc
        except Exception:
            # read_document документирует единый тип ошибки, но обещание —
            # не гарантия: сорвись что-то незаявленное, временный файл всё
            # равно не должен остаться висеть без строки в базе, которая
            # дала бы коучу его увидеть или удалить.
            _discard_staging(staging_path, folder)
            raise

        prepared = prepare_measurements(context.references, read.table)

        added_at = datetime.now()
        with context.session() as repo:
            document = repo.documents.add(
                snapshot_id,
                file.filename or "без имени",
                "",
                added_at,
                unparsed=read.table.unparsed,
            )
            stored_path = folder / f"{document.id}{suffix}"
            staging_path.rename(stored_path)
            repo.documents.set_stored_path(document.id, str(stored_path))

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
        # один раз: сколько показателей вошло и из какого документа.
        # Страница рендерится напрямую — тем же приёмом, что и загрузка
        # анкеты в routes_snapshots.py.
        with context.session() as repo:
            snapshot = repo.snapshots.get(snapshot_id)
            if snapshot is None:
                raise HTTPException(
                    status_code=404, detail=f"нет среза {snapshot_id}"
                )
            client = repo.clients.get(snapshot.client_code)
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
                    header=read.lines[:HEADER_LINES],
                    client_name=client.full_name if client else "",
                    belongs=(
                        document_belongs_to(client, read.lines) if client else True
                    ),
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
            measurement = next(
                (
                    m
                    for m in repo.snapshots.measurements(snapshot_id)
                    if m.id == measurement_id
                ),
                None,
            )
            if measurement is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"в срезе {snapshot_id} нет показателя {measurement_id}",
                )
            # Строка существует, но не пуста — set_value заполняет только
            # пропуск. 404 здесь означал бы коучу, что его число потерялось,
            # хотя оно на месте: двойная отправка или отклик по старой
            # вкладке — не то же самое, что опечатка в идентификаторе.
            if measurement.value is not None or not repo.snapshots.set_value(
                measurement_id, snapshot_id, number
            ):
                raise HTTPException(status_code=409, detail="число уже вписано")
        return RedirectResponse(f"/snapshots/{snapshot_id}#показатели", status_code=303)

    return router


def _discard_staging(staging_path: Path, folder: Path) -> None:
    """Убрать временный файл неудачной загрузки и, если это была
    единственная попытка для этого среза, пустую папку за ним следом.

    `rmdir` отказывает на непустой папке — ничего не задев, если в ней уже
    лежит документ прежней успешной загрузки или чужая параллельная
    загрузка успела дописать свой файл первой.
    """
    staging_path.unlink(missing_ok=True)
    with suppress(OSError):
        folder.rmdir()


def _coach_facing(exc: DocumentError, staging_path: Path, file: UploadFile) -> str:
    """Сообщение об ошибке с именем файла коуча, а не служебным именем на
    диске, и один раз, а не дважды.

    `read_document` заворачивает причину в DocumentError, добавляя перед
    ней имя файла на диске (`staging_path.name`, вроде «a1b2…9f.pdf»); если
    причина сама уже начиналась с того же имени (так делает `read_pdf_lines`
    и часть сообщений OCR), оно оказывается упомянуто дважды подряд. Коуч
    не знает и не должен знать это служебное имя — он загружал «бланк.pdf».
    """
    stored_name = staging_path.name
    original_name = file.filename or "файл"
    message = str(exc)
    message = message.replace(f"{stored_name}: {stored_name}: ", f"{stored_name}: ")
    return message.replace(stored_name, original_name)
