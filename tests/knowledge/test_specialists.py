from pathlib import Path

import pytest

from healthcoach.knowledge.specialists import SpecialistsError, load_specialists

SPEC = Path(__file__).parents[2] / "knowledge" / "specialists.yaml"


def test_loads_specialties():
    s = load_specialists(SPEC)
    endo = s.specialty("эндокринолог")
    assert endo is not None
    assert endo.name == "Эндокринолог"
    assert "щитовидн" in endo.when.lower()


def test_doctors_attached_to_specialty():
    s = load_specialists(SPEC)
    endo = s.specialty("эндокринолог")
    assert len(endo.doctors) >= 1
    assert endo.doctors[0].contacts


def test_public_view_omits_doctors_entirely():
    s = load_specialists(SPEC)
    public = s.public_view()

    assert public
    for entry in public:
        assert set(entry) == {"id", "название", "когда"}

    serialized = repr(public)
    for specialty in s.specialties:
        for doctor in specialty.doctors:
            assert doctor.name not in serialized
            assert doctor.contacts not in serialized


def test_unknown_specialty_returns_none():
    assert load_specialists(SPEC).specialty("нет_такой") is None


def test_duplicate_specialty_id_raises(tmp_path):
    path = tmp_path / "s.yaml"
    path.write_text(
        "специальности:\n"
        "  - id: дубль\n"
        "    название: Дубль\n"
        "    когда: Всегда\n"
        "  - id: дубль\n"
        "    название: Дубль ещё раз\n"
        "    когда: Всегда\n",
        encoding="utf-8",
    )
    with pytest.raises(SpecialistsError, match="дубль"):
        load_specialists(path)


def test_specialty_without_when_raises(tmp_path):
    path = tmp_path / "s.yaml"
    path.write_text(
        "специальности:\n  - id: x\n    название: Икс\n",
        encoding="utf-8",
    )
    with pytest.raises(SpecialistsError, match="когда"):
        load_specialists(path)
