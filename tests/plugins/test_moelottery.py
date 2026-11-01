"""moelottery 的属性池抽取与模板渲染 (不依赖 bot)."""

from __future__ import annotations

import random
from pathlib import Path

import pytest
from mbplugin_moelottery.lottery import LotteryBox, weighted_choice
from mbplugin_moelottery.typedefs import (
    AttrPool,
    ComputedAttr,
    MoeData,
    PoolDependency,
    SuffixRule,
)


def _data() -> MoeData:
    return MoeData(
        template="{derived}:{cond}",
        computed={
            "derived": ComputedAttr(
                depends_on="base",
                mapping={"fire": "hot"},
                default="mild",
            )
        },
        suffix_rules=[SuffixRule(condition="{cond}", text="!")],
        pools={
            # 条件池故意放在独立池前面, lot() 必须分两轮
            "cond": AttrPool(
                label="条件",
                depends_on=PoolDependency(pool="base", triggers={"fire": {"burn": 1}}),
            ),
            "base": AttrPool(label="基础", options={"fire": 1, "water": 1}),
        },
    )


def _box(tmp_path: Path) -> LotteryBox:
    path = tmp_path / "moe.json"
    path.write_text(_data().model_dump_json(), encoding="utf-8")
    return LotteryBox(str(path))


def test_conditional_pool_is_drawn_after_its_dependency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    box = _box(tmp_path)
    monkeypatch.setattr(
        "mbplugin_moelottery.lottery.weighted_choice",
        lambda options: next(iter(options)),
    )

    assert box.lot() == {"base": "fire", "cond": "burn"}


def test_dependency_miss_produces_none() -> None:
    assert (
        LotteryBox._draw_from_pool(
            AttrPool(
                label="条件",
                depends_on=PoolDependency(pool="base", triggers={"fire": {"burn": 1}}),
            ),
            {"base": "water"},
        )
        is None
    )


def test_nullable_pool_can_return_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = AttrPool(label="可空", options={"x": 1}, nullable=True, null_weight=10)
    monkeypatch.setattr(random, "uniform", lambda _a, _b: 1.0)
    assert LotteryBox._draw_from_pool(pool, {}) is None


def test_weighted_choice_passes_weights(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], list[int], int]] = []

    def fake_choices(keys: list[str], *, weights: list[int], k: int) -> list[str]:
        calls.append((keys, weights, k))
        return [keys[1]]

    monkeypatch.setattr(random, "choices", fake_choices)
    assert weighted_choice({"a": 1, "b": 2}) == "b"
    assert calls == [(["a", "b"], [1, 2], 1)]


def test_build_response_text_uses_computed_values_and_suffixes(
    tmp_path: Path,
) -> None:
    box = _box(tmp_path)
    assert box.build_response_text({"base": "fire", "cond": "burn"}) == "hot:burn!"
    assert box.build_response_text({"base": "water", "cond": None}) == "mild:"
