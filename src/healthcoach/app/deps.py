"""Состояние приложения: база знаний и доступ к базе данных.

База знаний читается один раз при запуске: она неизменна и общая для всех
запросов. Соединение с базой данных — наоборот, своё на каждый запрос.
FastAPI выполняет синхронные обработчики в пуле рабочих потоков, а
sqlite3.Connection принадлежит потоку, в котором создан; общее соединение
падало бы с ProgrammingError на первом же обращении. Заодно соединения не
копятся: каждое закрывается по выходе из запроса.

Контекст передаётся явно, чтобы тесты поднимали приложение поверх временной
базы без монкипатчинга.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from healthcoach.intake.ocr import AppleVisionEngine, OCREngine
from healthcoach.knowledge.coach import Coach, load_coach
from healthcoach.knowledge.questionnaire import Questionnaire, load_questionnaire
from healthcoach.knowledge.references import References, load_references
from healthcoach.knowledge.specialists import Specialists, load_specialists
from healthcoach.llm.provider import ClaudeCodeProvider, LLMProvider
from healthcoach.storage.clients import ClientRepository
from healthcoach.storage.db import open_database
from healthcoach.storage.documents import DocumentRepository
from healthcoach.storage.drafts import DraftRepository
from healthcoach.storage.requests import RequestRepository
from healthcoach.storage.snapshots import SnapshotRepository


@dataclass(frozen=True)
class Repositories:
    """Хранилища поверх одного соединения, живущего один запрос."""

    clients: ClientRepository
    snapshots: SnapshotRepository
    documents: DocumentRepository
    requests: RequestRepository
    drafts: DraftRepository


@dataclass(frozen=True)
class Context:
    questionnaire: Questionnaire
    references: References
    specialists: Specialists
    coach: Coach
    documents_dir: Path
    database_path: Path
    ocr: OCREngine | None
    llm: LLMProvider

    @contextmanager
    def session(self) -> Iterator[Repositories]:
        """Открыть соединение на время одного запроса и закрыть его."""
        connection = open_database(self.database_path)
        try:
            yield Repositories(
                clients=ClientRepository(connection),
                snapshots=SnapshotRepository(connection),
                documents=DocumentRepository(connection),
                requests=RequestRepository(connection),
                drafts=DraftRepository(connection),
            )
        finally:
            connection.close()


def build_context(data_dir: Path, knowledge_dir: Path) -> Context:
    """Собрать состояние приложения из папок с данными и базой знаний."""
    documents_dir = data_dir / "documents"
    documents_dir.mkdir(parents=True, exist_ok=True)
    database_path = data_dir / "healthcoach.db"
    open_database(database_path).close()

    # Распознавание есть только в macOS. Без него PDF читаются как обычно,
    # а фотография честно отвечает, что распознать её нечем.
    engine: OCREngine | None
    try:
        engine = AppleVisionEngine()
    except Exception:
        engine = None

    return Context(
        questionnaire=load_questionnaire(knowledge_dir / "questionnaire.yaml"),
        references=load_references(knowledge_dir / "references"),
        specialists=load_specialists(knowledge_dir / "specialists.yaml"),
        coach=load_coach(knowledge_dir / "coach.yaml"),
        documents_dir=documents_dir,
        database_path=database_path,
        ocr=engine,
        llm=ClaudeCodeProvider(),
    )
