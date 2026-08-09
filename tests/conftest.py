from pathlib import Path

import pytest

SAMPLES = Path(__file__).parents[1] / "samples"


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "samples: работает на настоящих выгрузках из samples/ (пропускается, "
        "если папки нет — там персональные данные, в репозиторий они не попадают)",
    )
    config.addinivalue_line(
        "markers",
        "llm: делает живой вызов языковой модели (пропускается, если она "
        "недоступна — расходует лимиты подписки)",
    )


@pytest.fixture
def samples_dir() -> Path:
    if not SAMPLES.is_dir():
        pytest.skip("папки samples/ нет — тест на живых выгрузках пропущен")
    return SAMPLES
