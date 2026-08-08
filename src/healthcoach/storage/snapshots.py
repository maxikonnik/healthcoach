"""Срезы клиента: измерения и ответы опросника.

Модуль оперирует только кодом клиента и не имеет доступа к его имени.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date

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
    value: float
    units: str
    taken_on: date
    confirmed: bool


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
        units=row["units"],
        taken_on=date.fromisoformat(row["taken_on"]),
        confirmed=bool(row["confirmed"]),
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
        value: float,
        units: str,
        taken_on: date,
        document_id: int | None = None,
    ) -> StoredMeasurement:
        cursor = self._connection.execute(
            "INSERT INTO measurements "
            "(snapshot_id, analyte_id, raw_name, value, units, taken_on, document_id, confirmed) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
            (
                snapshot_id,
                analyte_id,
                raw_name,
                value,
                units,
                taken_on.isoformat(),
                document_id,
            ),
        )
        self._connection.commit()
        return StoredMeasurement(
            id=cursor.lastrowid,
            analyte_id=analyte_id,
            raw_name=raw_name,
            value=value,
            units=units,
            taken_on=taken_on,
            confirmed=False,
        )

    def measurements(self, snapshot_id: int) -> list[StoredMeasurement]:
        rows = self._connection.execute(
            "SELECT * FROM measurements WHERE snapshot_id = ? ORDER BY id",
            (snapshot_id,),
        ).fetchall()
        return [_measurement(row) for row in rows]

    def confirm_measurement(self, measurement_id: int) -> None:
        self._connection.execute(
            "UPDATE measurements SET confirmed = 1 WHERE id = ?", (measurement_id,)
        )
        self._connection.commit()

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
