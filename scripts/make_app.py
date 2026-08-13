# -*- coding: utf-8 -*-
"""Собрать «Health Coaching.app» — значок для запуска инструмента.

Двойной щелчок поднимает локальный сервер и открывает браузер. Приложение
живёт в Dock, пока инструмент работает; выход из него останавливает сервер.

Запуск сборки:

    uv run python scripts/make_app.py

Значок рисуется здесь же, без сторонних библиотек: в проекте нет и не
должно появляться зависимости ради одной картинки. PNG пишется вручную
(zlib + структура чанков), остальное делает системный `sips`/`iconutil`.
"""

from __future__ import annotations

import math
import plistlib
import shutil
import struct
import subprocess
import zlib
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
APP_NAME = "Health Coaching"
PORT = 8765

_UV_CANDIDATES = (
    Path.home() / ".local" / "bin" / "uv",
    Path("/opt/homebrew/bin/uv"),
    Path("/usr/local/bin/uv"),
)


def _find_uv() -> Path:
    """Путь к `uv` — абсолютный, а не по PATH.

    Приложение, запущенное двойным щелчком, не читает профиль оболочки:
    PATH у него системный, и `uv` из ~/.local/bin в него не входит. Путь
    вшивается при сборке, а запускающий скрипт всё равно перепроверяет
    его на месте — переустановка `uv` не должна ломать значок молча.
    """
    for candidate in _UV_CANDIDATES:
        if candidate.exists():
            return candidate
    found = shutil.which("uv")
    if found:
        return Path(found)
    raise SystemExit("не найден uv — установите его или поправьте _UV_CANDIDATES")


# --- рисование значка ---------------------------------------------------

_BG_TOP = (0x4F, 0x9A, 0x6A)
_BG_BOTTOM = (0x2C, 0x66, 0x42)
_LINE = (0xFF, 0xFF, 0xFF)

_PULSE = (
    (0.11, 0.53), (0.33, 0.53), (0.41, 0.30),
    (0.50, 0.74), (0.58, 0.38), (0.66, 0.53), (0.89, 0.53),
)
"""Линия пульса: ровный ход, всплеск, возврат. Кардиограмма читается
значком здоровья без подписи и не спорит с тем, что инструмент делает."""


def _rounded_box_distance(x: float, y: float, size: float, radius: float) -> float:
    half = size / 2
    qx = abs(x - half) - (half - radius)
    qy = abs(y - half) - (half - radius)
    outside = math.hypot(max(qx, 0.0), max(qy, 0.0))
    return outside + min(max(qx, qy), 0.0) - radius


def _segment_distance(px, py, ax, ay, bx, by) -> float:
    vx, vy = bx - ax, by - ay
    wx, wy = px - ax, py - ay
    length2 = vx * vx + vy * vy
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, (wx * vx + wy * vy) / length2))
    return math.hypot(wx - t * vx, wy - t * vy)


def _draw_master(size: int) -> bytes:
    """Нарисовать значок и вернуть его как RGBA-строку."""
    radius = size * 0.225
    line_half = size * 0.050
    pulse = [(x * size, y * size) for x, y in _PULSE]

    pixels = bytearray(size * size * 4)

    for y in range(size):
        mix = y / (size - 1)
        base = tuple(
            round(_BG_TOP[i] + (_BG_BOTTOM[i] - _BG_TOP[i]) * mix) for i in range(3)
        )
        row = y * size * 4
        for x in range(size):
            distance = _rounded_box_distance(x + 0.5, y + 0.5, size, radius)
            alpha = min(1.0, max(0.0, 0.5 - distance))
            offset = row + x * 4
            pixels[offset] = base[0]
            pixels[offset + 1] = base[1]
            pixels[offset + 2] = base[2]
            pixels[offset + 3] = round(alpha * 255)

    # Линия рисуется только рядом с собой: обход всего полотна на каждый
    # отрезок стоил бы минуты на тысяче пикселей и ничего бы не добавил.
    for index in range(len(pulse) - 1):
        ax, ay = pulse[index]
        bx, by = pulse[index + 1]
        pad = line_half + 2
        x0 = max(0, int(min(ax, bx) - pad))
        x1 = min(size - 1, int(max(ax, bx) + pad))
        y0 = max(0, int(min(ay, by) - pad))
        y1 = min(size - 1, int(max(ay, by) + pad))
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                distance = _segment_distance(x + 0.5, y + 0.5, ax, ay, bx, by)
                coverage = min(1.0, max(0.0, line_half - distance + 0.5))
                if coverage <= 0:
                    continue
                offset = (y * size + x) * 4
                for channel in range(3):
                    old = pixels[offset + channel]
                    pixels[offset + channel] = round(
                        old + (_LINE[channel] - old) * coverage
                    )
    return bytes(pixels)


def _write_png(path: Path, size: int, rgba: bytes) -> None:
    raw = bytearray()
    stride = size * 4
    for y in range(size):
        raw.append(0)  # фильтр строки: без предсказания
        raw.extend(rgba[y * stride : (y + 1) * stride])

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


def _build_icns(work: Path) -> Path:
    master_size = 512
    master = work / "master.png"
    _write_png(master, master_size, _draw_master(master_size))

    iconset = work / "AppIcon.iconset"
    iconset.mkdir()
    for size in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            pixels = size * scale
            name = f"icon_{size}x{size}{'@2x' if scale == 2 else ''}.png"
            subprocess.run(
                ["sips", "-z", str(pixels), str(pixels), str(master),
                 "--out", str(iconset / name)],
                check=True, capture_output=True,
            )
    icns = work / "AppIcon.icns"
    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(icns)],
                   check=True, capture_output=True)
    return icns


# --- запускающий скрипт -------------------------------------------------

_LAUNCHER = """#!/bin/bash
# Запуск инструмента по двойному щелчку. Собран scripts/make_app.py —
# правьте сборщик, а не этот файл: приложение пересобирается целиком.
set -u

PROJECT="{project}"
UV="{uv}"
PORT={port}
URL="http://127.0.0.1:$PORT"
LOG="$PROJECT/data/запуск.log"

fail() {{
    /usr/bin/osascript -e "display alert \\"Health Coaching не запустился\\" \\
message \\"$1\\n\\nПодробности: $LOG\\" as critical" >/dev/null 2>&1
    exit 1
}}

# Уже запущен из Терминала или вторым щелчком — просто открыть окно.
if /usr/bin/curl -s -o /dev/null -m 2 "$URL"; then
    /usr/bin/open "$URL"
    exit 0
fi

[ -x "$UV" ] || UV="$(/usr/bin/which uv 2>/dev/null || true)"
[ -x "$UV" ] || fail "не найден uv — переустановите его и пересоберите значок."
[ -d "$PROJECT" ] || fail "папка проекта не найдена: $PROJECT"

mkdir -p "$PROJECT/data"
echo "--- $(date '+%Y-%m-%d %H:%M:%S') запуск ---" >> "$LOG"

# Браузер открывается отдельно и только когда сервер ответит: окно,
# открытое раньше, показало бы ошибку соединения.
(
    for _ in $(seq 1 90); do
        if /usr/bin/curl -s -o /dev/null -m 2 "$URL"; then
            /usr/bin/open "$URL"
            exit 0
        fi
        sleep 1
    done
    /usr/bin/osascript -e "display alert \\"Health Coaching не отвечает\\" \\
message \\"Сервер не поднялся за полторы минуты.\\n\\nПодробности: $LOG\\" \\
as critical" >/dev/null 2>&1
) &

# exec, а не фоновый процесс: сервер становится самим приложением, и выход
# из него в Dock останавливает инструмент, не оставляя сервер висеть.
cd "$PROJECT" || fail "не удалось перейти в папку проекта"
exec "$UV" run python -m healthcoach.app.main >> "$LOG" 2>&1
"""


def build(destination: Path) -> Path:
    app = destination / f"{APP_NAME}.app"
    if app.exists():
        shutil.rmtree(app)

    contents = app / "Contents"
    macos = contents / "MacOS"
    resources = contents / "Resources"
    macos.mkdir(parents=True)
    resources.mkdir(parents=True)

    work = destination / ".значок-сборка"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir()
    try:
        shutil.copy(_build_icns(work), resources / "AppIcon.icns")
    finally:
        shutil.rmtree(work)

    launcher = macos / "HealthCoaching"
    launcher.write_text(
        _LAUNCHER.format(project=PROJECT, uv=_find_uv(), port=PORT),
        encoding="utf-8",
    )
    launcher.chmod(0o755)

    (contents / "Info.plist").write_bytes(
        plistlib.dumps(
            {
                "CFBundleName": APP_NAME,
                "CFBundleDisplayName": APP_NAME,
                "CFBundleExecutable": "HealthCoaching",
                "CFBundleIdentifier": "ru.healthcoach.launcher",
                "CFBundleIconFile": "AppIcon",
                "CFBundlePackageType": "APPL",
                "CFBundleShortVersionString": "1.0",
                "CFBundleVersion": "1",
                "LSMinimumSystemVersion": "12.0",
                "NSHighResolutionCapable": True,
            }
        )
    )

    # Finder кеширует значки по дате изменения бандла: без этого
    # пересобранное приложение показывалось бы со старой картинкой.
    subprocess.run(["touch", str(app)], check=False)
    return app


if __name__ == "__main__":
    built = build(PROJECT)
    print(f"собрано: {built}")
