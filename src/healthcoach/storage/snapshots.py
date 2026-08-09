"""Срезы клиента: измерения и ответы опросника.

Модуль оперирует только кодом клиента и не имеет доступа к его имени.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date

SOURCE_MANUAL = "ручной ввод"
SOURCE_PDF = "pdf"
SOURCE_PHOTO = "фото"

Answers = dict[str, int]


@dataclass(frozen=True)
class Snapshot:
    id: int
    client_code: str
    taken_on: date
    note: str | None


@dataclass(frozen=True)
class StoredMeasurement:
    id: int
    analyte_id: str
    raw_name: str
    value: float | None
    """None, если в бланке было не число: «<0.60» не равно 0.60."""
    raw_value: str
    units: str
    taken_on: date
    confirmed: bool
    source: str
    document_id: int | None


def _snapshot(row: sqlite3.Row) -> Snapshot:
    return Snapshot(
        id=row["id"],
        client_code=row["client_code"],
        taken_on=date.fromisoformat(row["taken_on"]),
        note=row["note"],
    )


def _measurement(row: sqlite3.Row) -> StoredMeasurement:
    return StoredMeasurement(
        id=row["id"],
        analyte_id=row["analyte_id"],
        raw_name=row["raw_name"],
        value=row["value"],
        raw_value=row["raw_value"],
        units=row["units"],
        taken_on=date.fromisoformat(row["taken_on"]),
        confirmed=bool(row["confirmed"]),
        source=row["source"],
        document_id=row["document_id"],
    )


class SnapshotRepository:
    """Срезы, измерения и ответы. Имён клиентов не видит."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def create(
        self, client_code: str, taken_on: date, note: str | None = None
    ) -> Snapshot:
        cursor = self._connection.execute(
            "INSERT INTO snapshots (client_code, taken_on, note) VALUES (?, ?, ?)",
            (client_code, taken_on.isoformat(), note),
        )
        self._connection.commit()
        return Snapshot(
            id=cursor.lastrowid, client_code=client_code, taken_on=taken_on, note=note
        )

    def get(self, snapshot_id: int) -> Snapshot | None:
        row = self._connection.execute(
            "SELECT * FROM snapshots WHERE id = ?", (snapshot_id,)
        ).fetchone()
        return _snapshot(row) if row is not None else None

    def for_client(self, client_code: str) -> list[Snapshot]:
        rows = self._connection.execute(
            "SELECT * FROM snapshots WHERE client_code = ? ORDER BY taken_on, id",
            (client_code,),
        ).fetchall()
        return [_snapshot(row) for row in rows]

    def add_measurement(
        self,
        snapshot_id: int,
        analyte_id: str,
        raw_name: str,
        value: float | None,
        raw_value: str,
        units: str,
        taken_on: date,
        source: str = SOURCE_MANUAL,
        document_id: int | None = None,
    ) -> StoredMeasurement:
        cursor = self._connection.execute(
            "INSERT INTO measurements "
            "(snapshot_id, analyte_id, raw_name, value, raw_value, units, "
            " taken_on, document_id, source, confirmed) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
            (
                snapshot_id,
                analyte_id,
                raw_name,
                value,
                raw_value,
                units,
                taken_on.isoformat(),
                document_id,
                source,
            ),
        )
        self._connection.commit()
        return StoredMeasurement(
            id=cursor.lastrowid,
            analyte_id=analyte_id,
            raw_name=raw_name,
            value=value,
            raw_value=raw_value,
            units=units,
            taken_on=taken_on,
            confirmed=False,
            source=source,
            document_id=document_id,
        )

    def measurements(self, snapshot_id: int) -> list[StoredMeasurement]:
        rows = self._connection.execute(
            "SELECT * FROM measurements WHERE snapshot_id = ? ORDER BY id",
            (snapshot_id,),
        ).fetchall()
        return [_measurement(row) for row in rows]

    def confirm_measurement(self, measurement_id: int, snapshot_id: int) -> bool:
        """Подтвердить измерение этого среза. False — такого измерения нет.

        Срез обязателен: без него подтверждение по одному лишь идентификатору
        затрагивало бы измерение любого другого клиента, а несуществующий
        идентификатор проходил бы как успех.
        """
        cursor = self._connection.execute(
            "UPDATE measurements SET confirmed = 1 "
            "WHERE id = ? AND snapshot_id = ?",
            (measurement_id, snapshot_id),
        )
        self._connection.commit()
        return cursor.rowcount == 1

    def set_value(self, measurement_id: int, snapshot_id: int, value: float) -> bool:
        """Вписать число там, где в бланке его не было. False — строки нет,
        либо число там уже есть.

        Срез обязателен по той же причине, что и у подтверждения: без него
        правка по одному идентификатору затрагивала бы измерение любого
        другого клиента. Условие `value IS NULL` — по причине, ради которой
        метод существует: он заполняет пропуск, а не переписывает число,
        которое коуч уже мог подтвердить как верное.
        """
        cursor = self._connection.execute(
            "UPDATE measurements SET value = ? "
            "WHERE id = ? AND snapshot_id = ? AND value IS NULL",
            (value, measurement_id, snapshot_id),
        )
        self._connection.commit()
        return cursor.rowcount == 1

    def history(self, client_code: str, analyte_id: str) -> list[StoredMeasurement]:
        """Все измерения показателя по клиенту, по дате забора."""
        rows = self._connection.execute(
            "SELECT m.* FROM measurements m "
            "JOIN snapshots s ON s.id = m.snapshot_id "
            "WHERE s.client_code = ? AND m.analyte_id = ? "
            "ORDER BY m.taken_on, m.id",
            (client_code, analyte_id),
        ).fetchall()
        return [_measurement(row) for row in rows]

    def save_answers(self, snapshot_id: int, answers: Answers) -> None:
        """Заменить ответы среза целиком."""
        with self._connection:
            self._connection.execute(
                "DELETE FROM answers WHERE snapshot_id = ?", (snapshot_id,)
            )
            self._connection.executemany(
                "INSERT INTO answers (snapshot_id, question_id, score) VALUES (?, ?, ?)",
                [(snapshot_id, qid, score) for qid, score in answers.items()],
            )

    def answers(self, snapshot_id: int) -> Answers:
        rows = self._connection.execute(
            "SELECT question_id, score FROM answers WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchall()
        return {row["question_id"]: row["score"] for row in rows}
