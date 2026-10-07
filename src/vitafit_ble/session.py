"""Measurement session over an open GATT connection."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from typing import TYPE_CHECKING

from .protocol import (
    ACK_IMPEDANCE,
    ACK_STABLE_WEIGHT,
    HELLO_COMMANDS,
    ImpedanceFrame,
    WeightFrame,
    decode,
)

if TYPE_CHECKING:
    from bleak import BleakClient
    from bleak.backends.characteristic import BleakGATTCharacteristic

_LOGGER = logging.getLogger(__name__)

NOTIFY_CHARACTERISTIC_UUID = "0000fff1-0000-1000-8000-00805f9b34fb"
WRITE_CHARACTERISTIC_UUID = "0000fff2-0000-1000-8000-00805f9b34fb"

WEIGHT_TIMEOUT = 30.0
IMPEDANCE_TIMEOUT = 6.0


@dataclass(frozen=True, slots=True)
class Measurement:
    """Result of one weigh-in."""

    weight_kg: float
    impedance_ohm: int | None


async def _async_next_frame(
    frames: asyncio.Queue[bytes],
) -> WeightFrame | ImpedanceFrame | None:
    data = await frames.get()
    frame = decode(data)
    _LOGGER.debug("Received %s: %s", data.hex(" "), frame)
    return frame


async def _async_stable_weight(frames: asyncio.Queue[bytes]) -> WeightFrame:
    while True:
        frame = await _async_next_frame(frames)
        if isinstance(frame, WeightFrame) and frame.stable:
            return frame


async def _async_impedance(frames: asyncio.Queue[bytes]) -> ImpedanceFrame:
    while True:
        frame = await _async_next_frame(frames)
        if isinstance(frame, ImpedanceFrame):
            return frame


async def async_measure(
    client: BleakClient,
    *,
    weight_timeout: float = WEIGHT_TIMEOUT,
    impedance_timeout: float = IMPEDANCE_TIMEOUT,
) -> Measurement | None:
    """Run one weigh-in; return None if no stable weight arrives in time.

    Impedance is None if the scale does not report it in time, for example
    when the user steps off early or is wearing socks.
    """
    frames: asyncio.Queue[bytes] = asyncio.Queue()

    def _on_notify(_: BleakGATTCharacteristic, data: bytearray) -> None:
        frames.put_nowait(bytes(data))

    async def _async_write(command: bytes) -> None:
        _LOGGER.debug("Sending %s", command.hex(" "))
        await client.write_gatt_char(WRITE_CHARACTERISTIC_UUID, command, response=True)

    await client.start_notify(NOTIFY_CHARACTERISTIC_UUID, _on_notify)
    for command in HELLO_COMMANDS:
        await _async_write(command)

    try:
        async with asyncio.timeout(weight_timeout):
            weight = await _async_stable_weight(frames)
    except TimeoutError:
        return None

    # Acknowledging the stable weight starts the impedance measurement.
    await _async_write(ACK_STABLE_WEIGHT)
    try:
        async with asyncio.timeout(impedance_timeout):
            impedance = await _async_impedance(frames)
    except TimeoutError:
        return Measurement(weight_kg=weight.weight_kg, impedance_ohm=None)

    await _async_write(ACK_IMPEDANCE)
    return Measurement(
        weight_kg=weight.weight_kg, impedance_ohm=impedance.impedance_ohm
    )
