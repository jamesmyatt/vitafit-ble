"""Frame codec tests.

Vectors are from openScale's VitafitVT701HandlerTest, captured from real weigh-ins.
"""

import pytest

from vitafit_ble.protocol import (
    ACK_IMPEDANCE,
    ACK_STABLE_WEIGHT,
    HELLO_COMMANDS,
    ImpedanceFrame,
    WeightFrame,
    decode,
)


def h(text: str) -> bytes:
    return bytes.fromhex(text)


def test_stable_weight() -> None:
    assert decode(h("5a 0a 26 10 02 00 00 21 21 34 0a aa")) == WeightFrame(
        weight_kg=85.0, stable=True
    )


def test_settling_weight() -> None:
    assert decode(h("5a 0a 26 10 01 00 00 21 21 43 7e aa")) == WeightFrame(
        weight_kg=85.15, stable=False
    )


@pytest.mark.parametrize(
    ("frame", "ohm"),
    [
        ("5a 0b 26 11 00 00 00 00 00 01 89 b4 aa", 393),
        ("5a 0b 26 11 00 00 00 00 00 01 85 b8 aa", 389),
    ],
)
def test_impedance(frame: str, ohm: int) -> None:
    assert decode(h(frame)) == ImpedanceFrame(impedance_ohm=ohm)


@pytest.mark.parametrize(
    "frame",
    [
        "5a 0a 26 10 02 00 00 21 21 34 ff aa",  # bad checksum
        "5a 0b 26 11 00 00 00 00 00 01 89 ff aa",  # bad checksum
        "5a 0a 00 10 02 00 00 21 24 a9 b4 aa",  # wrong product byte
        "5a 0b 26 11 00 00 00 00 00 00 00 3c aa",  # zero impedance
        "0000000000",  # truncated
        "",
    ],
)
def test_rejected(frame: str) -> None:
    assert decode(h(frame)) is None


def test_commands() -> None:
    assert (
        h("a5 05 26 33 00 10 aa"),
        h("a5 04 26 44 66 aa"),
        h("a5 05 26 17 01 35 aa"),
    ) == HELLO_COMMANDS
    assert h("a5 05 26 10 02 31 aa") == ACK_STABLE_WEIGHT
    assert h("a5 05 26 11 00 32 aa") == ACK_IMPEDANCE
