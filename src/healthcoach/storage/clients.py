"""Реестр клиентов.

Единственное место, где ФИО и контакты покидают базу. Всё остальное
приложение оперирует кодом клиента: обезличивание в плане 3 опирается
на то, что реестр не читается ниоткуда больше.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date

from healthcoach.knowledge.sex import normalize_sex

CODE_PREFIX = "CL-"
CODE_DIGITS = 4


@dataclass(frozen=True)
class Client:
    """Клиент коуча.

    Пол и дата рождения обязательны: почти каждый целевой коридор в базе
    знаний задан для пола и возрастного диапазона, и без них находки
    считались бы для кого-то другого. Возраст не хранится — он считается
    на дату забора анализа и потому не устаревает.
    """

    code: str
    full_name: str
    sex: str
    birth_date: date
    contacts: str | None
    note: str | None

    def age_on(self, when: date) -> int:
        """Полных лет на указанную дату."""
        years = when.year - self.birth_date.year
        if (when.month, when.day) < (self.birth_date.month, self.birth_date.day):
            years -= 1
        return years


def _client(row: sqlite3.Row) -> Client:
    return Client(
        code=row["code"],
        full_name=row["full_name"],
        sex=row["sex"],
        birth_date=date.fromisoformat(row["birth_date"]),
        contacts=row["contacts"],
        note=row["note"],
    )


class ClientRepository:
    """Клиенты и соответствие кода реальному имени."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def next_code(self) -> str:
        """Следующий свободный код вида CL-0007."""
        rows = self._connection.execute("SELECT code FROM identities").fetchall()
        used = {
            int(row["code"][len(CODE_PREFIX) :])
            for row in rows
            if row["code"].startswith(CODE_PREFIX)
            and row["code"][len(CODE_PREFIX) :].isdigit()
        }
        return f"{CODE_PREFIX}{max(used, default=0) + 1:0{CODE_DIGITS}d}"

    def add(
        self,
        full_name: str,
        sex: str,
        birth_date: date,
        contacts: str | None = None,
        note: str | None = None,
    ) -> Client:
        if not full_name.strip():
            raise ValueError("ФИО клиента не может быть пустым")
        normalized_sex = normalize_sex(sex)
        code = self.next_code()
        client = Client(
            code=code,
            full_name=full_name.strip(),
            sex=normalized_sex,
            birth_date=birth_date,
            contacts=contacts,
            note=note,
        )
        self._connection.execute(
            "INSERT INTO identities (code, full_name, sex, birth_date, contacts, note) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                code,
                client.full_name,
                normalized_sex,
                birth_date.isoformat(),
                contacts,
                note,
            ),
        )
        self._connection.commit()
        return client

    def get(self, code: str) -> Client | None:
        row = self._connection.execute(
            "SELECT * FROM identities WHERE code = ?", (code,)
        ).fetchone()
        return _client(row) if row is not None else None

    def all(self) -> list[Client]:
        rows = self._connection.execute(
            "SELECT * FROM identities ORDER BY code"
        ).fetchall()
        return [_client(row) for row in rows]
