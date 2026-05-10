"""Smart Grid scenario JSON shape tests.

Verifies the Phase-2 conversion of single-file scenarios → AOB array format
keeps every record loadable as a :class:`evaluation.models.Scenario`.

These tests skip when ``src/evaluation/`` is unavailable (Phase 1 branch
not merged into Phase 2 branch yet — the evaluation module lives on
``aob/sg-evaluation-adapter`` while these scenarios live on
``aob/sg-domain-port``).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# Skip the entire module if Phase 1's evaluation module isn't present on the
# current branch.
pytest.importorskip("evaluation.models", reason="evaluation/ from Phase 1 not on this branch")

from evaluation.models import Scenario  # noqa: E402  (import-after-skip)


_SCENARIOS_DIR = Path(__file__).resolve().parents[3] / "scenarios" / "local"


def _load(filename: str) -> list[dict]:
    path = _SCENARIOS_DIR / filename
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(raw, list), f"{filename} must be a JSON array"
    return raw


def test_smart_grid_scenarios_count():
    records = _load("smart_grid.json")
    # Phase-2 floor: 11 hand-picked subset → expanded to the full HPML
    # 31-scenario corpus (HPML #15 closed at 15+, HPML #33 closed at 30+)
    # → 61-scenario corpus after the HPML #55 / AOB #36 50+ expansion
    # ports SGT-031..SGT-050 (gap-fill, including the 5 generated promoted
    # in HPML PR #195) and SGT-051..SGT-060 (capability-targeted batch
    # carrying the new optional benchmark_design + must_NOT_include
    # fields). AOB-FMSR-001 is the original AOB-style scenario; the
    # other 60 are SGT-NNN ports from data/scenarios/*.json in the HPML
    # repo, format-identical (same field set, same ground_truth shape).
    assert len(records) == 61


def test_smart_grid_negative_checks_count():
    records = _load("smart_grid_negative_checks.json")
    assert len(records) == 5


def test_smart_grid_scenarios_validate_via_aob_scenario_model():
    for raw in _load("smart_grid.json"):
        scenario = Scenario.from_raw(raw)
        assert scenario.id
        assert scenario.text
        # Permissive extra='allow' should preserve domain-specific fields.
        assert hasattr(scenario, "asset_id") or "asset_id" not in raw


def test_smart_grid_negative_checks_validate_via_aob_scenario_model():
    for raw in _load("smart_grid_negative_checks.json"):
        scenario = Scenario.from_raw(raw)
        assert scenario.id.startswith("SG-NEG-")


def test_smart_grid_scenario_ids_unique():
    main = _load("smart_grid.json")
    neg = _load("smart_grid_negative_checks.json")
    ids = [r["id"] for r in main + neg]
    assert len(ids) == len(set(ids)), f"duplicate scenario IDs detected: {ids}"


def test_smart_grid_capability_targeted_rubric_fields_preserved():
    """Guard against silent drop of the discriminative rubric fields added
    in the 50+ expansion (AOB #36).

    The capability-targeted batch (SGT-051..SGT-060) carries
    ``benchmark_design.target_capability`` + ``discrimination_hypothesis``,
    and SGT-051..SGT-060 plus three reframed reconciliation scenarios
    (SGT-037, SGT-038, SGT-046) carry ``ground_truth.must_NOT_include``.
    These fields are central to the discrimination story for that
    sub-batch; ``Scenario`` uses ``extra='allow'`` which preserves them
    today, but a future copy / serializer change could silently drop
    them while keeping every other test green.

    Use count-anchored assertions so the test survives cosmetic ID
    reorders or renames; the absolute floors match the current corpus
    composition.
    """
    records = _load("smart_grid.json")

    bd_records = [r for r in records if "benchmark_design" in r]
    mnot_records = [
        r for r in records
        if isinstance(r.get("ground_truth"), dict)
        and "must_NOT_include" in r["ground_truth"]
    ]

    assert len(bd_records) >= 10, (
        f"benchmark_design preserved on {len(bd_records)}/61 records; "
        "expected >= 10 (SGT-051..SGT-060)"
    )
    assert len(mnot_records) >= 13, (
        f"must_NOT_include preserved on {len(mnot_records)}/61 records; "
        "expected >= 13 (SGT-037, SGT-038, SGT-046, SGT-051..SGT-060)"
    )

    # Every benchmark_design record must carry the two sub-fields that
    # back the discrimination claim — silent shape erosion is the failure
    # mode this test exists to catch.
    for r in bd_records:
        bd = r["benchmark_design"]
        assert isinstance(bd, dict), f"{r['id']}: benchmark_design must be a dict"
        assert bd.get("target_capability"), (
            f"{r['id']}: benchmark_design.target_capability missing or empty"
        )
        assert bd.get("discrimination_hypothesis"), (
            f"{r['id']}: benchmark_design.discrimination_hypothesis missing or empty"
        )

    # must_NOT_include must be a non-empty list of strings; an empty
    # array would silently pass any downstream "agent did not produce X"
    # check.
    for r in mnot_records:
        mnot = r["ground_truth"]["must_NOT_include"]
        assert isinstance(mnot, list) and mnot, (
            f"{r['id']}: ground_truth.must_NOT_include must be a non-empty list"
        )
        assert all(isinstance(x, str) and x for x in mnot), (
            f"{r['id']}: ground_truth.must_NOT_include entries must be non-empty strings"
        )


def test_smart_grid_capability_targeted_fields_survive_model_roundtrip():
    """The new optional fields must survive a ``Scenario.from_raw`` →
    ``.model_dump()`` round-trip.

    ``Scenario`` declares ``ConfigDict(extra='allow')`` which preserves
    unknown fields on load and dumps them back by default, but a future
    model upgrade that changes extras handling would silently strip the
    discrimination-rubric fields. This test catches that regression.
    """
    records = _load("smart_grid.json")

    for raw in records:
        if "benchmark_design" not in raw and (
            not isinstance(raw.get("ground_truth"), dict)
            or "must_NOT_include" not in raw["ground_truth"]
        ):
            continue

        dumped = Scenario.from_raw(raw).model_dump()

        if "benchmark_design" in raw:
            assert "benchmark_design" in dumped, (
                f"{raw['id']}: benchmark_design dropped on model round-trip"
            )
            assert (
                dumped["benchmark_design"].get("target_capability")
                == raw["benchmark_design"].get("target_capability")
            ), f"{raw['id']}: target_capability mutated on round-trip"

        if (
            isinstance(raw.get("ground_truth"), dict)
            and "must_NOT_include" in raw["ground_truth"]
        ):
            dumped_gt = dumped.get("ground_truth")
            assert isinstance(dumped_gt, dict) and "must_NOT_include" in dumped_gt, (
                f"{raw['id']}: ground_truth.must_NOT_include dropped on round-trip"
            )
            assert (
                dumped_gt["must_NOT_include"]
                == raw["ground_truth"]["must_NOT_include"]
            ), f"{raw['id']}: must_NOT_include mutated on round-trip"
