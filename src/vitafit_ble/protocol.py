"""Frame codec for the Vitafit VT701 GATT protocol.

Frames in both directions are ``[header][length][0x26][type][data…][checksum][0xAA]``:

- ``header`` is 0x5A from the scale and 0xA5 from the client.
- ``length`` counts every byte after itself.
- ``checksum`` is the XOR of ``length`` through the last data byte.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import reduce
from operator import xor

HEADER_SCALE = 0x5A
HEADER_CLIENT = 0xA5
PRODUCT_ID = 0x26
TRAILER = 0xAA

TYPE_WEIGHT = 0x10
TYPE_IMPEDANCE = 0x11
TYPE_HELLO_1 = 0x33
TYPE_HELLO_2 = 0x44
TYPE_HELLO_3 = 0x17

STABLE_FLAG = 0x02

MIN_FRAME_LENGTH = 6
WEIGHT_FRAME_LENGTH = 12
IMPEDANCE_FRAME_LENGTH = 13

# Impedance outside this range is treated as no reading.
IMPEDANCE_MIN_OHM = 1
IMPEDANCE_MAX_OHM = 1499


@dataclass(frozen=True, slots=True)
class WeightFrame:
    """Live weight reading."""

    weight_kg: float
    stable: bool


@dataclass(frozen=True, slots=True)
class ImpedanceFrame:
    """Whole-body impedance reading."""

    impedance_ohm: int


def _checksum(data: bytes) -> int:
    return reduce(xor, data, 0)


def encode_command(frame_type: int, data: bytes = b"") -> bytes:
    """Build a client-to-scale command frame."""
    body = bytes((len(data) + 4, PRODUCT_ID, frame_type)) + data
    return bytes((HEADER_CLIENT,)) + body + bytes((_checksum(body), TRAILER))


HELLO_COMMANDS = (
    encode_command(TYPE_HELLO_1, b"\x00"),
    encode_command(TYPE_HELLO_2),
    encode_command(TYPE_HELLO_3, b"\x01"),
)
ACK_STABLE_WEIGHT = encode_command(TYPE_WEIGHT, bytes((STABLE_FLAG,)))
ACK_IMPEDANCE = encode_command(TYPE_IMPEDANCE, b"\x00")


def _is_valid(frame: bytes) -> bool:
    return (
        len(frame) >= MIN_FRAME_LENGTH
        and frame[0] == HEADER_SCALE
        and frame[1] == len(frame) - 2
        and frame[2] == PRODUCT_ID
        and frame[-1] == TRAILER
        and _checksum(frame[1:-2]) == frame[-2]
    )


def decode(frame: bytes) -> WeightFrame | ImpedanceFrame | None:
    """Decode a scale-to-client frame; return None if invalid or unrecognised."""
    if not _is_valid(frame):
        return None
    frame_type = frame[3]
    if frame_type == TYPE_WEIGHT and len(frame) == WEIGHT_FRAME_LENGTH:
        raw = int.from_bytes(frame[8:10], "big")
        return WeightFrame(weight_kg=raw / 100, stable=frame[4] == STABLE_FLAG)
    if frame_type == TYPE_IMPEDANCE and len(frame) == IMPEDANCE_FRAME_LENGTH:
        ohm = int.from_bytes(frame[9:11], "big")
        if IMPEDANCE_MIN_OHM <= ohm <= IMPEDANCE_MAX_OHM:
            return ImpedanceFrame(impedance_ohm=ohm)
    return None
