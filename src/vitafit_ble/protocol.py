"""Frame codec for the Vitafit VT701 GATT protocol.

Frames in both directions are ``[header][length][0x26][type][data…][checksum][0xAA]``:

- ``header`` is 0x5A from the scale and 0xA5 from the client.
- ``length`` counts every byte after itself.
- ``checksum`` is the XOR of ``length`` through the last data byte.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from functools import cache, reduce
import logging
from operator import xor
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator

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
WEIGHT_FRAME_LENGTH = 12
IMPEDANCE_FRAME_LENGTH = 13


class WeightFlag(IntEnum):
    """Weight frame flag: how far the reading has got."""

    NO_LOAD = 0x00
    """Nobody is on the scale."""
    MEASURING = 0x01
    """The reading is settling."""
    STABLE = 0x02
    """The reading has settled."""


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
class Frame:
    """Base class for decoded scale-to-client frames."""


@dataclass(frozen=True, slots=True)
class WeightFrame(Frame):
    """Live weight reading."""

    weight_kg: float
    """Weight in kg, to 0.01 kg, whatever the display unit."""
    flag: int
    """How far the reading has got: a WeightFlag, or the raw value if unknown."""
    display_unit: DisplayUnit | None
    """Unit the scale is displaying; None if the unit code is unknown."""

    @property
    def stable(self) -> bool:
        """True once the reading has settled (``flag`` is WeightFlag.STABLE)."""
        return self.flag == WeightFlag.STABLE


@dataclass(frozen=True, slots=True)
class ImpedanceFrame(Frame):
    """Whole-body impedance reading."""

    impedance_ohm: int | None
    """Impedance in Ω; None if the scale couldn't measure it, e.g. through socks."""
    code: int | None = None
    """The raw value when ``impedance_ohm`` is None; None for a reading.

    An ImpedanceCode if it's a known one, otherwise the out-of-range value.
    """


def _checksum(data: Iterable[int]) -> int:
    return reduce(xor, data, 0)


def encode_command(frame_type: FrameType, data: bytes = b"") -> bytes:
    """Build a client-to-scale command frame."""
    # Typed wrapper: functools.cache hides the arguments' types from mypy.
    return _encode_command(frame_type, data)


@cache
def _encode_command(frame_type: FrameType, data: bytes) -> bytes:
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


def ack_command(frame: WeightFrame | ImpedanceFrame) -> bytes:
    """Build the acknowledgement of a decoded weight or impedance frame.

    A weight acknowledgement echoes the frame's flag, as the Vitafit app does.
    An impedance acknowledgement is always the same.
    """
    match frame:
        case WeightFrame(flag=flag):
            return encode_command(FrameType.WEIGHT, bytes((flag,)))
        case ImpedanceFrame():  # pragma: no branch
            return encode_command(FrameType.IMPEDANCE, b"\x00")


def _is_valid(frame: bytes) -> bool:
    return (
        len(frame) >= MIN_FRAME_LENGTH
        and frame[0] == HEADER_SCALE
        and frame[1] == len(frame) - 2
        and frame[2] == PRODUCT_ID
        and frame[-1] == TRAILER
        and _checksum(frame[1:-2]) == frame[-2]
    )


def _decode_weight(frame: bytes) -> WeightFrame | None:
    if len(frame) != WEIGHT_FRAME_LENGTH:
        _LOGGER.debug("Weight frame has wrong length: %s", frame.hex(" "))
        return None
    raw = int.from_bytes(frame[8:10], "big")
    try:
        flag: int = WeightFlag(frame[4])
    except ValueError:
        flag = frame[4]
    try:
        display_unit: DisplayUnit | None = DisplayUnit(frame[7] - UNIT_BASE)
    except ValueError:
        display_unit = None
    return WeightFrame(weight_kg=raw / 100, flag=flag, display_unit=display_unit)


def _decode_impedance(frame: bytes) -> ImpedanceFrame | None:
    if len(frame) != IMPEDANCE_FRAME_LENGTH:
        _LOGGER.debug("Impedance frame has wrong length: %s", frame.hex(" "))
        return None
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
            return ImpedanceFrame(impedance_ohm=None, code=ohm)
    return ImpedanceFrame(impedance_ohm=None, code=ImpedanceCode(ohm))


# Decoder for each frame type that decode() turns into a Frame. Other valid
# frames, such as the command replies, aren't decoded.
_DECODERS: dict[int, Callable[[bytes], WeightFrame | ImpedanceFrame | None]] = {
    FrameType.WEIGHT: _decode_weight,
    FrameType.IMPEDANCE: _decode_impedance,
}


def decode(frame: bytes) -> WeightFrame | ImpedanceFrame | None:
    """Decode a scale-to-client frame; return None if invalid or unrecognised."""
    if not _is_valid(frame):
        return None
    decoder = _DECODERS.get(frame[3])
    return decoder(frame) if decoder else None
