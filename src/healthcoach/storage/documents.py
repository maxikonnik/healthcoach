"""Файлы выгрузок, приложенные к срезу.

В базе лежит только путь: сами файлы остаются на диске в папке данных,
которую закрывает .gitignore. Внутри выгрузки — ФИО пациента, дата
рождения, адрес и номер полиса, и попасть в репозиторий они не должны.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Document:
    id: int
    snapshot_id: int
    filename: str
    stored_path: str
    added_at: datetime
    unparsed: tuple[str, ...]
    """Строки бланка, которые разбор не смог превратить в запись, — считаны
    один раз при загрузке и хранятся с документом. Перечитывать файл (а для
    фотографии — заново распознавать) при каждом открытии среза стоило бы
    секунд на каждый просмотр страницы."""


def _document(row: sqlite3.Row) -> Document:
    return Document(
        id=row["id"],
        snapshot_id=row["snapshot_id"],
        filename=row["filename"],
        stored_path=row["stored_path"],
        added_at=datetime.fromisoformat(row["added_at"]),
        unparsed=tuple(json.loads(row["unparsed"])) if row["unparsed"] else (),
    )


class DocumentRepository:
    """Выгрузки лабораторий, приложенные к срезам."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add(
        self,
        snapshot_id: int,
        filename: str,
        stored_path: str,
        added_at: datetime,
        unparsed: Sequence[str] = (),
    ) -> Document:
        cursor = self._connection.execute(
            "INSERT INTO documents "
            "(snapshot_id, filename, stored_path, added_at, unparsed) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                snapshot_id,
                filename,
                stored_path,
                added_at.isoformat(),
                json.dumps(list(unparsed), ensure_ascii=False),
            ),
        )
        self._connection.commit()
        return Document(
            id=cursor.lastrowid,
            snapshot_id=snapshot_id,
            filename=filename,
            stored_path=stored_path,
            added_at=added_at,
            unparsed=tuple(unparsed),
        )

    def set_stored_path(self, document_id: int, stored_path: str) -> None:
        """Записать настоящий путь файла на диске.

        Имя файла на диске — идентификатор документа, а его знает только
        база после вставки строки; отсюда и отдельный шаг после `add`,
        а не единственный INSERT со всеми полями сразу.
        """
        self._connection.execute(
            "UPDATE documents SET stored_path = ? WHERE id = ?",
            (stored_path, document_id),
        )
        self._connection.commit()

    def get(self, document_id: int) -> Document | None:
        row = self._connection.execute(
            "SELECT * FROM documents WHERE id = ?", (document_id,)
        ).fetchone()
        return _document(row) if row is not None else None

    def for_snapshot(self, snapshot_id: int) -> list[Document]:
        rows = self._connection.execute(
            "SELECT * FROM documents WHERE snapshot_id = ? ORDER BY id",
            (snapshot_id,),
        ).fetchall()
        return [_document(row) for row in rows]
