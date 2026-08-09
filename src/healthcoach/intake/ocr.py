"""Распознавание текста с фотографии бланка.

Движок вынесен за интерфейс: сегодня это встроенное в macOS
распознавание — оффлайн, бесплатно, медицинские данные не покидают
машину коуча. Разбор строк от движка не зависит.

Распознавание возвращает наблюдения, а не строки таблицы: название
показателя и его значение приходят отдельно, потому что колонки далеко
друг от друга. Строка собирается по вертикальной координате.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class OCRError(Exception):
    """Изображение не распознано."""


@dataclass(frozen=True)
class TextLine:
    """Наблюдение распознавания. Координаты — доли от размера изображения."""

    text: str
    x: float
    y: float


class OCREngine(Protocol):
    """Движок распознавания. Меняется целиком, не по частям."""

    def read(self, path: Path) -> list[TextLine]: ...


def rows_from_observations(
    observations: Sequence[TextLine], tolerance: float = 0.006
) -> list[str]:
    """Собрать наблюдения в строки таблицы по вертикальной координате."""
    if not observations:
        return []

    ordered = sorted(observations, key=lambda o: -o.y)
    rows: list[list[TextLine]] = [[ordered[0]]]
    for observation in ordered[1:]:
        if abs(rows[-1][0].y - observation.y) > tolerance:
            rows.append([])
        rows[-1].append(observation)

    return [
        " ".join(o.text for o in sorted(row, key=lambda o: o.x)) for row in rows
    ]


class AppleVisionEngine:
    """Распознавание средствами macOS."""

    def __init__(self, languages: Sequence[str] = ("ru-RU", "en-US")) -> None:
        self._languages = list(languages)

    def read(self, path: Path) -> list[TextLine]:
        try:
            import Quartz
            import Vision
            from Foundation import NSURL
        except ImportError as exc:
            raise OCRError(
                "распознавание доступно только в macOS: не найден Vision"
            ) from exc

        url = NSURL.fileURLWithPath_(str(path))
        source = Quartz.CGImageSourceCreateWithURL(url, None)
        image = (
            Quartz.CGImageSourceCreateImageAtIndex(source, 0, None)
            if source is not None
            else None
        )
        if image is None:
            raise OCRError(f"{path.name}: файл не распознан как изображение")

        request = Vision.VNRecognizeTextRequest.alloc().init()
        request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        request.setRecognitionLanguages_(self._languages)
        request.setUsesLanguageCorrection_(True)

        handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(
            image, None
        )
        handler.performRequests_error_([request], None)

        observations: list[TextLine] = []
        for result in request.results() or ():
            candidates = result.topCandidates_(1)
            if not candidates:
                continue
            box = result.boundingBox()
            observations.append(
                TextLine(
                    text=candidates[0].string(),
                    x=box.origin.x,
                    y=box.origin.y + box.size.height / 2,
                )
            )
        return observations
