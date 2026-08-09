"""Запрос клиента и его цели — его словами.

Хранятся две версии: то, что написал клиент, и то, что коуч вычитал для
отправки модели. Затирать исходную нельзя: коуч должен видеть, что именно
он убрал, и вернуть, если ошибся.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class ClientRequest:
    snapshot_id: int
    raw: str
    redacted: str
    approved: bool


def _request(row: sqlite3.Row) -> ClientRequest:
    return ClientRequest(
        snapshot_id=row["snapshot_id"],
        raw=row["raw"],
        redacted=row["redacted"],
        approved=bool(row["approved"]),
    )


class RequestRepository:
    """Запрос клиента по срезу."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def save(self, snapshot_id: int, raw: str) -> ClientRequest:
        """Записать запрос. Прежняя вычитка и утверждение сбрасываются.

        Клиент переписал текст — значит вычитка относилась к другому тексту,
        и утверждать её заново обязан коуч.
        """
        self._connection.execute(
            "INSERT INTO requests (snapshot_id, raw, redacted, approved) "
            "VALUES (?, ?, '', 0) "
            "ON CONFLICT(snapshot_id) DO UPDATE SET raw = excluded.raw, "
            "redacted = '', approved = 0",
            (snapshot_id, raw),
        )
        self._connection.commit()
        return ClientRequest(
            snapshot_id=snapshot_id, raw=raw, redacted="", approved=False
        )

    def set_redacted(self, snapshot_id: int, redacted: str) -> bool:
        """Записать вычитанный текст. False — запроса нет."""
        cursor = self._connection.execute(
            "UPDATE requests SET redacted = ?, approved = 0 WHERE snapshot_id = ?",
            (redacted, snapshot_id),
        )
        self._connection.commit()
        return cursor.rowcount == 1

    def approve(self, snapshot_id: int) -> bool:
        """Подтвердить, что вычитанный текст можно отправлять.

        False — запроса нет или коуч ещё не вычитал: утверждать нечего.
        """
        cursor = self._connection.execute(
            "UPDATE requests SET approved = 1 "
            "WHERE snapshot_id = ? AND redacted != ''",
            (snapshot_id,),
        )
        self._connection.commit()
        return cursor.rowcount == 1

    def get(self, snapshot_id: int) -> ClientRequest | None:
        row = self._connection.execute(
            "SELECT * FROM requests WHERE snapshot_id = ?", (snapshot_id,)
        ).fetchone()
        return _request(row) if row is not None else None
