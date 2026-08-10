"""Набор срезов, по которому собирается отчёт.

Отчёт по-прежнему принадлежит одному срезу — самому свежему из выбранных.
Эта таблица хранит только то, какие ещё срезы коуч отметил галочками при
сборке: она не про то, где лежит отчёт, а про то, что видит интерпретация.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable


class ReportScopeRepository:
    """Набор срезов по владеющему срезу отчёта."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def set_members(self, snapshot_id: int, member_ids: Iterable[int]) -> None:
        """Заменить набор целиком одной транзакцией.

        Пустой набор запрещён: отчёт не может опираться на ноль срезов, а
        молчаливая подстановка `[snapshot_id]` здесь была бы догадкой —
        вызывающий обязан явно передать хотя бы один срез.

        Утверждённый черновик набор замораживает (правило 6). Проверка
        стоит здесь, а не только в маршруте, ровно как в
        `drafts.save_section`: между проверкой в маршруте и записью
        утверждение может пройти во второй вкладке, и утверждённый отчёт
        поменял бы состав задним числом. Маршрут ловит `ValueError` и
        отвечает 409 — тем же способом, что и на разделах черновика.
        """
        ids = list(member_ids)
        if not ids:
            raise ValueError(
                f"срез {snapshot_id}: набор срезов отчёта не может быть пустым"
            )
        approved = self._connection.execute(
            "SELECT 1 FROM draft_approvals WHERE snapshot_id = ?", (snapshot_id,)
        ).fetchone()
        if approved is not None:
            raise ValueError(
                f"черновик среза {snapshot_id} утверждён — набор срезов не меняется"
            )
        with self._connection:
            self._connection.execute(
                "DELETE FROM report_snapshots WHERE snapshot_id = ?", (snapshot_id,)
            )
            self._connection.executemany(
                "INSERT OR IGNORE INTO report_snapshots "
                "(snapshot_id, member_snapshot_id) VALUES (?, ?)",
                [(snapshot_id, member_id) for member_id in ids],
            )

    def members(self, snapshot_id: int) -> list[int]:
        """Сохранённый набор по возрастанию id.

        Если записей нет, срез трактуется как набор из самого себя — это
        объявленное поведение по умолчанию (правило 7 плана), а не догадка:
        все существующие срезы продолжают работать без миграции данных.
        """
        rows = self._connection.execute(
            "SELECT member_snapshot_id FROM report_snapshots "
            "WHERE snapshot_id = ? ORDER BY member_snapshot_id",
            (snapshot_id,),
        ).fetchall()
        if not rows:
            return [snapshot_id]
        return [row["member_snapshot_id"] for row in rows]
