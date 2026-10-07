"""Frame codec for the Vitafit VT701 GATT protocol.

Frames in both directions are ``[header][length][0x26][type][data…][checksum][0xAA]``:

- ``header`` is 0x5A from the scale and 0xA5 from the client.
- ``length`` counts every byte after itself.
- ``checksum`` is the XOR of ``length`` through the last data byte.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from functools import reduce
import logging
from operator import xor
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

_LOGGER = logging.getLogger(__name__)

HEADER_SCALE = 0x5A
HEADER_CLIENT = 0xA5
PRODUCT_ID = 0x26
TRAILER = 0xAA

MODE_NORMAL = 0x00
# The Vitafit app's weight-only mode: the scale passes no current and sends
# impedance 0x55AA.
MODE_WEIGHT_ONLY = 0x01

# Weight frame byte 7 is UNIT_BASE + the current display unit, but the weight
# itself is always sent in 0.01 kg.
UNIT_BASE = 0x20

STABLE_FLAG = 0x02

MIN_FRAME_LENGTH = 6

# Impedance outside this range is treated as no reading, as openScale does.
IMPEDANCE_MIN_OHM = 1
IMPEDANCE_MAX_OHM = 1499


class FrameType(IntEnum):
    """Frame type byte, the same in both directions."""

    WEIGHT = 0x10
    IMPEDANCE = 0x11
    UNIT = 0x17
    """Sets the scale's display unit; the data byte is a DisplayUnit.

    It isn't needed for a weigh-in, so the session only sends it when asked to
    set the unit.
    """
    MODE = 0x33
    """Sets the measurement mode; the data byte is MODE_NORMAL or MODE_WEIGHT_ONLY.

    The scale keeps the mode until the next mode command, including for
    weigh-ins without a connection. openScale calls this the first hello.
    """
    HELLO = 0x44
    """Unknown request, referred to as the hello command.

    The scale replies with one data byte of unknown meaning, 0x00 so far.
    """


# Total length of each scale-to-client frame type that decode() reads.
FRAME_LENGTHS: dict[int, int] = {FrameType.WEIGHT: 12, FrameType.IMPEDANCE: 13}


class ImpedanceCode(IntEnum):
    """Impedance values that mean the scale didn't measure it."""

    FAILED = 0xFFFF
    """No contact, for example through socks."""
    WEIGHT_ONLY = 0x55AA
    """The scale is in weight-only mode, so it passed no current."""


class DisplayUnit(IntEnum):
    """Unit shown on the scale's display. Readings are always sent in kg."""

    KG = 1
    LB = 2
    ST = 3


@dataclass(frozen=True, slots=True)
class WeightFrame:
    """Live weight reading."""

    weight_kg: float
    """Weight in kg, to 0.01 kg, whatever the display unit."""
    stable: bool
    """True once the reading has settled."""
    display_unit: DisplayUnit | None
    """Unit the scale is displaying; None if the unit code is unknown."""


@dataclass(frozen=True, slots=True)
class ImpedanceFrame:
    """Whole-body impedance reading."""

    impedance_ohm: int | None
    """Impedance in Ω; None if the scale couldn't measure it, e.g. through socks."""


def _checksum(data: Iterable[int]) -> int:
    return reduce(xor, data, 0)


def encode_command(frame_type: FrameType, data: bytes = b"") -> bytes:
    """Build a client-to-scale command frame."""
    body = (len(data) + 4, PRODUCT_ID, frame_type, *data)
    return bytes((HEADER_CLIENT, *body, _checksum(body), TRAILER))


def unit_command(unit: DisplayUnit) -> bytes:
    """Build the command that sets the scale's display unit."""
    return encode_command(FrameType.UNIT, bytes((unit,)))


def start_commands(
    *, weight_only: bool = False, display_unit: DisplayUnit | None = None
) -> Iterator[bytes]:
    """Yield the commands sent at the start of a weigh-in.

    The scale starts the weigh-in by itself when it wakes; these set it up.

    The mode command, then the hello command, then the unit command if
    ``display_unit`` is given.
    """
    mode = MODE_WEIGHT_ONLY if weight_only else MODE_NORMAL
    yield encode_command(FrameType.MODE, bytes((mode,)))
    yield encode_command(FrameType.HELLO)
    if display_unit is not None:
        yield unit_command(display_unit)


ACK_STABLE_WEIGHT = encode_command(FrameType.WEIGHT, bytes((STABLE_FLAG,)))
ACK_IMPEDANCE = encode_command(FrameType.IMPEDANCE, b"\x00")


def _is_valid(frame: bytes) -> bool:
    if not (
        len(frame) >= MIN_FRAME_LENGTH
        and frame[0] == HEADER_SCALE
        and frame[1] == len(frame) - 2
        and frame[2] == PRODUCT_ID
        and frame[-1] == TRAILER
        and _checksum(frame[1:-2]) == frame[-2]
    ):
        return False
    expected = FRAME_LENGTHS.get(frame[3])
    if expected is not None and len(frame) != expected:
        _LOGGER.debug(
            "%s frame has wrong length: %s",
            FrameType(frame[3]).name.capitalize(),
            frame.hex(" "),
        )
        return False
    return True


def _decode_weight(frame: bytes) -> WeightFrame:
    raw = int.from_bytes(frame[8:10], "big")
    try:
        display_unit: DisplayUnit | None = DisplayUnit(frame[7] - UNIT_BASE)
    except ValueError:
        display_unit = None
    return WeightFrame(
        weight_kg=raw / 100,
        stable=frame[4] == STABLE_FLAG,
        display_unit=display_unit,
    )


def _decode_impedance(frame: bytes) -> ImpedanceFrame:
    ohm = int.from_bytes(frame[9:11], "big")
    match ohm:
        case ImpedanceCode.FAILED:
            _LOGGER.debug("Impedance not measured: no contact, e.g. socks")
        case ImpedanceCode.WEIGHT_ONLY:
            _LOGGER.debug("Impedance not measured: weight-only mode")
        case _ if IMPEDANCE_MIN_OHM <= ohm <= IMPEDANCE_MAX_OHM:
            return ImpedanceFrame(impedance_ohm=ohm)
        case _:
            _LOGGER.debug("Impedance out of range: %s Ω", ohm)
    # Still a valid frame, unlike None, so the session acks it and stops waiting.
    return ImpedanceFrame(impedance_ohm=None)


def decode(frame: bytes) -> WeightFrame | ImpedanceFrame | None:
    """Decode a scale-to-client frame; return None if invalid or unrecognised."""
    if not _is_valid(frame):
        return None
    match frame[3]:
        case FrameType.WEIGHT:
            return _decode_weight(frame)
        case FrameType.IMPEDANCE:
            return _decode_impedance(frame)
    return None
