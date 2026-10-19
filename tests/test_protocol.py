"""Frame codec tests, using frames captured from a real VT701 (see frames.py)."""

from __future__ import annotations

import logging

import pytest

from vitafit_ble.protocol import (
    DisplayUnit,
    ImpedanceCode,
    ImpedanceFrame,
    WeightFlag,
    WeightFrame,
    ack_command,
    decode,
    start_commands,
    unit_command,
)

from .frames import (
    IMPEDANCE,
    IMPEDANCE_FAILED,
    IMPEDANCE_WEIGHT_ONLY,
    NO_LOAD,
    NO_LOAD_LB,
    SETTLING,
    SETTLING_LB,
    SETTLING_ST,
    STABLE,
    STABLE_LB,
    STABLE_SOCKS,
    STABLE_ST,
    START_REPLIES,
    UNIT_ACK,
    h,
)


@pytest.mark.parametrize(
    ("frame", "expected"),
    [
        (
            NO_LOAD,
            WeightFrame(0.0, flag=WeightFlag.NO_LOAD, display_unit=DisplayUnit.KG),
        ),
        # Display in lb or st: the weight bytes are still 0.01 kg.
        (
            NO_LOAD_LB,
            WeightFrame(0.0, flag=WeightFlag.NO_LOAD, display_unit=DisplayUnit.LB),
        ),
        (
            SETTLING_LB,
            WeightFrame(87.7, flag=WeightFlag.MEASURING, display_unit=DisplayUnit.LB),
        ),
        (
            SETTLING_ST,
            WeightFrame(87.5, flag=WeightFlag.MEASURING, display_unit=DisplayUnit.ST),
        ),
        (
            STABLE_LB,
            WeightFrame(87.2, flag=WeightFlag.STABLE, display_unit=DisplayUnit.LB),
        ),
        (
            STABLE_ST,
            WeightFrame(87.2, flag=WeightFlag.STABLE, display_unit=DisplayUnit.ST),
        ),
        (
            SETTLING,
            WeightFrame(87.4, flag=WeightFlag.MEASURING, display_unit=DisplayUnit.KG),
        ),
        (
            STABLE,
            WeightFrame(87.35, flag=WeightFlag.STABLE, display_unit=DisplayUnit.KG),
        ),
        (
            STABLE_SOCKS,
            WeightFrame(88.5, flag=WeightFlag.STABLE, display_unit=DisplayUnit.KG),
        ),
        # Unknown unit code (byte 7 0x2f).
        (
            h("5a 0a 26 10 01 00 00 2f 22 24 14 aa"),
            WeightFrame(87.4, flag=WeightFlag.MEASURING, display_unit=None),
        ),
        # Unknown flag (byte 4 0x05): kept as the raw value.
        (
            h("5a 0a 26 10 05 00 00 21 22 24 1e aa"),
            WeightFrame(87.4, flag=5, display_unit=DisplayUnit.KG),
        ),
    ],
)
def test_weight(frame: bytes, expected: WeightFrame) -> None:
    result = decode(frame)
    assert result == expected
    assert isinstance(result, WeightFrame)
    assert type(result.flag) is type(expected.flag)
    # Worked out from the flag: only a stable flag is stable.
    assert result.stable == (expected.flag == WeightFlag.STABLE)


def test_impedance() -> None:
    assert decode(IMPEDANCE) == ImpedanceFrame(impedance_ohm=466)


@pytest.mark.parametrize(
    ("frame", "code", "message"),
    [
        (IMPEDANCE_FAILED, ImpedanceCode.FAILED, "no contact"),
        (IMPEDANCE_WEIGHT_ONLY, ImpedanceCode.WEIGHT_ONLY, "weight-only mode"),
        # 1500 ohm: just above openScale's range, not a known code.
        (h("5a 0b 26 11 00 00 00 00 00 05 dc e5 aa"), 1500, "out of range: 1500"),
    ],
)
def test_impedance_failed(
    frame: bytes, code: int, message: str, caplog: pytest.LogCaptureFixture
) -> None:
    """A skipped impedance keeps the raw value as its code."""
    with caplog.at_level(logging.DEBUG, logger="vitafit_ble.protocol"):
        result = decode(frame)
    assert result == ImpedanceFrame(impedance_ohm=None, code=code)
    assert isinstance(result, ImpedanceFrame)
    assert type(result.code) is type(code)
    assert message in caplog.text


@pytest.mark.parametrize("frame", [*START_REPLIES, UNIT_ACK])
def test_command_replies_ignored(frame: bytes) -> None:
    assert decode(frame) is None


@pytest.mark.parametrize(
    "frame",
    [
        h("5a 0a 26 10 02 00 00 21 22 1f ff aa"),  # bad checksum
        h("5a 0b 26 11 00 00 00 00 00 01 d2 ff aa"),  # bad checksum
        h("5a 0a 00 10 02 00 00 21 22 1f 04 aa"),  # wrong product byte
        h("a5 05 26 10 02 31 aa"),  # client header
        h("0000000000"),  # truncated
        b"",
    ],
)
def test_rejected(frame: bytes) -> None:
    assert decode(frame) is None


@pytest.mark.parametrize(
    ("frame", "message"),
    [
        # Valid frames, except for one data byte too few.
        (h("5a 09 26 10 02 00 21 22 1f 21 aa"), "Weight frame has wrong length"),
        (h("5a 0a 26 11 00 00 00 00 01 d2 ee aa"), "Impedance frame has wrong length"),
    ],
)
def test_wrong_length(
    frame: bytes, message: str, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG, logger="vitafit_ble.protocol"):
        assert decode(frame) is None
    assert message in caplog.text


def test_commands() -> None:
    assert (
        h("a5 05 26 33 00 10 aa"),
        h("a5 04 26 44 66 aa"),
    ) == tuple(start_commands())
    assert (
        h("a5 05 26 33 01 11 aa"),  # captured from the Vitafit app
        h("a5 04 26 44 66 aa"),
    ) == tuple(start_commands(weight_only=True))
    assert (
        *start_commands(),
        unit_command(DisplayUnit.KG),
    ) == tuple(start_commands(display_unit=DisplayUnit.KG))
    assert h("a5 05 26 17 01 35 aa") == unit_command(DisplayUnit.KG)  # captured
    assert h("a5 05 26 17 02 36 aa") == unit_command(DisplayUnit.LB)  # captured
    assert h("a5 05 26 17 03 37 aa") == unit_command(DisplayUnit.ST)  # captured


@pytest.mark.parametrize(
    ("frame", "ack"),
    [
        # No load: the Vitafit app doesn't acknowledge it.
        (NO_LOAD, None),
        (SETTLING, h("a5 05 26 10 01 32 aa")),  # Vitafit app
        (STABLE, h("a5 05 26 10 02 31 aa")),  # openScale
        # Unknown flag (0x05): no known acknowledgement.
        (h("5a 0a 26 10 05 00 00 21 22 24 1e aa"), None),
        (IMPEDANCE, h("a5 05 26 11 00 32 aa")),  # openScale
        (IMPEDANCE_FAILED, h("a5 05 26 11 00 32 aa")),
    ],
)
def test_ack_command(frame: bytes, ack: bytes | None) -> None:
    """A weight acknowledgement echoes the frame's flag, if the app acks it."""
    decoded = decode(frame)
    assert decoded is not None
    assert ack_command(decoded) == ack


def test_ack_command_plain_int_flag() -> None:
    """A flag given as a plain int is acknowledged like the WeightFlag."""
    frame = WeightFrame(87.35, flag=2, display_unit=DisplayUnit.KG)
    assert frame.stable
    assert ack_command(frame) == h("a5 05 26 10 02 31 aa")
