"""Черновик отчёта: что написала модель и что оставил коуч.

У раздела два текста. Перезаписывать сгенерированное правкой значит
потерять возможность сравнить и переспросить. Утверждение замораживает
черновик: после него разделы не переписываются, иначе клиент получит не
то, что коуч утвердил.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

# Раздел склеивает finding_ids через "\n" и режет по нему обратно —
# без экранирования. Id находок сегодня внутренние (мы их формируем сами,
# не берём от клиента), но если это когда-нибудь изменится, id с переводом
# строки внутри тихо порвёт кортеж на два.
_SEPARATOR = "\n"


@dataclass(frozen=True)
class DraftSection:
    id: int
    snapshot_id: int
    section_id: str
    generated: str
    edited: str
    finding_ids: tuple[str, ...]

    @property
    def text(self) -> str:
        """Что пойдёт в отчёт: правка коуча, если она есть."""
        return self.edited or self.generated


def _section(row: sqlite3.Row) -> DraftSection:
    raw = row["finding_ids"]
    return DraftSection(
        id=row["id"],
        snapshot_id=row["snapshot_id"],
        section_id=row["section_id"],
        generated=row["generated"],
        edited=row["edited"],
        finding_ids=tuple(line for line in raw.split(_SEPARATOR) if line),
    )


class DraftRepository:
    """Разделы черновика по срезу."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def save_section(
        self,
        snapshot_id: int,
        section_id: str,
        generated: str,
        finding_ids: tuple[str, ...],
    ) -> DraftSection:
        if self.approved_at(snapshot_id) is not None:
            raise ValueError(
                f"черновик среза {snapshot_id} утверждён — разделы не переписываются"
            )
        self._connection.execute(
            "INSERT INTO draft_sections "
            "(snapshot_id, section_id, generated, edited, finding_ids) "
            "VALUES (?, ?, ?, '', ?) "
            "ON CONFLICT(snapshot_id, section_id) DO UPDATE SET "
            "generated = excluded.generated, edited = '', "
            "finding_ids = excluded.finding_ids",
            (snapshot_id, section_id, generated, _SEPARATOR.join(finding_ids)),
        )
        self._connection.commit()
        row = self._connection.execute(
            "SELECT * FROM draft_sections WHERE snapshot_id = ? AND section_id = ?",
            (snapshot_id, section_id),
        ).fetchone()
        return _section(row)

    def edit_section(self, section_row_id: int, snapshot_id: int, text: str) -> bool:
        """Записать правку коуча. False — раздела нет в этом срезе.

        После утверждения — исключение, не False: это не «раздела нет», а
        «правку внести нельзя», и вызывающий обязан различать эти случаи.
        """
        if self.approved_at(snapshot_id) is not None:
            raise ValueError(
                f"черновик среза {snapshot_id} утверждён — правки не вносятся"
            )
        cursor = self._connection.execute(
            "UPDATE draft_sections SET edited = ? WHERE id = ? AND snapshot_id = ?",
            (text, section_row_id, snapshot_id),
        )
        self._connection.commit()
        return cursor.rowcount == 1

    def sections(self, snapshot_id: int) -> list[DraftSection]:
        rows = self._connection.execute(
            "SELECT * FROM draft_sections WHERE snapshot_id = ? ORDER BY id",
            (snapshot_id,),
        ).fetchall()
        return [_section(row) for row in rows]

    def approve(
        self, snapshot_id: int, approved_at: datetime, knowledge: str = ""
    ) -> bool:
        """Заморозить черновик. False — черновика нет, замораживать нечего."""
        if not self.sections(snapshot_id):
            return False
        self._connection.execute(
            "INSERT INTO draft_approvals (snapshot_id, approved_at, knowledge) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(snapshot_id) DO UPDATE SET "
            "approved_at = excluded.approved_at, knowledge = excluded.knowledge",
            (snapshot_id, approved_at.isoformat(), knowledge),
        )
        self._connection.commit()
        return True

    def approved_at(self, snapshot_id: int) -> datetime | None:
        row = self._connection.execute(
            "SELECT approved_at FROM draft_approvals WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
        return datetime.fromisoformat(row["approved_at"]) if row is not None else None
