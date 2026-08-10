"""Разметка экрана находок на виде, собранном руками.

Часть состояний шкалы через маршрут не достать: они требуют такого
сочетания целевого коридора и лабораторного интервала, какого в
`knowledge/` этого репозитория просто нет. Шаблон здесь рисуется
напрямую — тем же движком и тем же `build_view`, что и в приложении, так
что проверяется настоящая разметка, а не её пересказ.
"""

from datetime import date
from types import SimpleNamespace

from jinja2 import Environment, FileSystemLoader

from healthcoach.app.main import TEMPLATES_DIR
from healthcoach.knowledge.references import Interval
from healthcoach.report.findings_view import build_view
from healthcoach.scoring.findings import KIND_ANALYTE, Finding
from healthcoach.scoring.references import STATUS_WITHIN


def _finding(**overrides) -> Finding:
    defaults = dict(
        kind=KIND_ANALYTE,
        subject_id="ферритин",
        title="Ферритин",
        value=65.0,
        units="нг/мл",
        status=STATUS_WITHIN,
        target=Interval(60, 70),
        lab_range=Interval(40, 100),
        note=None,
        rule_missing=False,
    )
    defaults.update(overrides)
    return Finding(**defaults)


def _render(findings) -> str:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True
    )
    return env.get_template("findings.html").render(
        snapshot=SimpleNamespace(id=1, taken_on=date(2026, 9, 1), client_code="CL-0001"),
        subject=SimpleNamespace(sex="ж"),
        age=36,
        view=build_view(findings),
    )


def test_target_band_of_zero_width_is_not_drawn_at_all():
    """Узкий коридор на широкой оси округляется в полосу нулевой ширины.

    «Нулевая ширина» задумана как «полосы не видно», но у `.scale-target`
    есть рамка, и при `box-sizing: border-box` два пикселя зелёного всё
    равно красятся у левого края — «коридор не задан» выглядит как
    «коридор в самом низу оси». Элемента, которому нечего показать, быть
    не должно вовсе.
    """
    finding = _finding(target=Interval(60, 70), lab_range=Interval(1, 10000))
    page = _render([finding])
    assert 'class="scale"' in page, "сама шкала при этом на месте"
    assert 'class="scale-target"' not in page


def test_target_band_with_real_width_is_drawn():
    """Обратная сторона: коридор, которому есть что показать, показан."""
    page = _render([_finding()])
    assert 'class="scale-target"' in page
    assert "width:0%" not in page


def test_normal_group_summary_is_not_painted_as_a_warning():
    """«В норме» — не предупреждение. Янтарный `.warn` там был скопирован
    со строки ниже, где он на месте."""
    page = _render([_finding()])
    assert "<summary>В норме" in page
    assert '<summary class="warn">В норме' not in page


def _dark_block(page: str) -> str:
    """Тело @media (prefers-color-scheme: dark) — по балансу скобок."""
    marker = "@media (prefers-color-scheme: dark)"
    assert marker in page, "тёмной схемы у страницы нет вовсе"
    start = page.index("{", page.index(marker))
    depth, index = 0, start
    while index < len(page):
        if page[index] == "{":
            depth += 1
        elif page[index] == "}":
            depth -= 1
            if depth == 0:
                return page[start + 1 : index]
        index += 1
    raise AssertionError("незакрытый блок тёмной схемы")


def test_every_new_scale_class_has_a_dark_scheme_of_its_own():
    """`color-scheme: light dark` объявлена в base.html, а цвета шкалы
    зашиты светлыми: на тёмном холсте полоса становится ярким островом, а
    вылет маркера за края полосы — тем, ради чего он и виден, — уходит
    тёмным по тёмному."""
    dark = _dark_block(_render([_finding()]))
    for selector in (".scale ", ".scale-target ", ".scale-mark "):
        assert selector in dark, f"{selector.strip()} остался светлым"


def test_the_dark_block_does_not_touch_the_pre_existing_colours():
    """`.tag` и `.step` жили здесь до шкалы, и их тёмная схема — отдельный
    вопрос: чинить его заодно значит смешать две правки в одной."""
    dark = _dark_block(_render([_finding()]))
    assert ".tag" not in dark
    assert ".step" not in dark
