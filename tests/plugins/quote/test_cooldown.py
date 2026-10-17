from mbplugin_quote.cooldown import Cooldown


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_expiry() -> None:
    clock = FakeClock()
    cd = Cooldown(10, clock=clock)
    assert cd.remaining("k") == 0
    cd.touch("k")
    clock.now = 4
    assert cd.remaining("k") == 6
    clock.now = 10
    assert cd.remaining("k") == 0
    assert len(cd) == 0


def test_capacity_evicts_oldest() -> None:
    clock = FakeClock()
    cd = Cooldown(10, capacity=2, clock=clock)
    for k in "abc":
        cd.touch(k)
    assert cd.remaining("a") == 0
    assert cd.remaining("c") == 10


def test_clear_undoes_touch() -> None:
    cd = Cooldown(10, clock=FakeClock())
    cd.touch("k")
    cd.clear("k")
    cd.clear("missing")
    assert cd.remaining("k") == 0


def test_zero_seconds_disables() -> None:
    cd = Cooldown(0, clock=FakeClock())
    cd.touch("k")
    assert cd.remaining("k") == 0
