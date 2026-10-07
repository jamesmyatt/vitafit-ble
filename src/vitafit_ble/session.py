"""Measurement session over an open GATT connection."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from typing import TYPE_CHECKING

from .const import (
    IMPEDANCE_TIMEOUT,
    NOTIFY_CHARACTERISTIC_UUID,
    WEIGHT_TIMEOUT,
    WRITE_CHARACTERISTIC_UUID,
)
from .protocol import (
    ACK_IMPEDANCE,
    ACK_STABLE_WEIGHT,
    ImpedanceFrame,
    WeightFrame,
    decode,
    start_commands,
)

if TYPE_CHECKING:
    from bleak import BleakClient
    from bleak.backends.characteristic import BleakGATTCharacteristic

    from .protocol import DisplayUnit

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Measurement:
    """Result of one weigh-in."""

    weight_kg: float
    """Stable weight in kg, to 0.01 kg."""
    impedance_ohm: int | None
    """Whole-body impedance in Ω.

    None if the scale couldn't measure it, for example through socks, or didn't
    report it in time, for example when the user stepped off early.
    """
    display_unit: DisplayUnit | None
    """Unit the scale was displaying, from the stable weight frame.

    None if the unit code is unknown.

    ``weight_kg`` is in kg whatever the display unit.
    """


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
    display_unit: DisplayUnit | None = None,
    weight_only: bool = False,
) -> Measurement | None:
    """Run one weigh-in; return None if no stable weight arrives in time.

    Impedance is None if the scale can't measure it, for example through socks,
    or doesn't report it in time, for example when the user steps off early.

    With ``display_unit``, set the scale's display unit after the mode and hello
    commands. Without it, the scale keeps its display unit. The weight is always
    in kg.

    With ``weight_only``, select the scale's weight-only mode, which passes no
    current, so impedance is None. Without it, select the normal mode. The
    scale keeps the mode for later weigh-ins without a connection.
    """
    frames: asyncio.Queue[bytes] = asyncio.Queue()

    def _on_notify(_: BleakGATTCharacteristic, data: bytearray) -> None:
        frames.put_nowait(bytes(data))

    async def _async_write(command: bytes) -> None:
        _LOGGER.debug("Sending %s", command.hex(" "))
        await client.write_gatt_char(WRITE_CHARACTERISTIC_UUID, command, response=True)

    await client.start_notify(NOTIFY_CHARACTERISTIC_UUID, _on_notify)
    for command in start_commands(weight_only=weight_only, display_unit=display_unit):
        await _async_write(command)

    try:
        async with asyncio.timeout(weight_timeout):
            weight = await _async_stable_weight(frames)
    except TimeoutError:
        _LOGGER.debug("No stable weight within %s s", weight_timeout)
        return None
    else:
        # openScale says acknowledging the stable weight starts the impedance
        # measurement. Untested: no normal-mode weigh-in has skipped it.
        await _async_write(ACK_STABLE_WEIGHT)

    try:
        async with asyncio.timeout(impedance_timeout):
            impedance = await _async_impedance(frames)
    except TimeoutError:
        _LOGGER.debug(
            "No impedance within %s s; returning weight only", impedance_timeout
        )
        impedance_ohm = None
    else:
        await _async_write(ACK_IMPEDANCE)
        impedance_ohm = impedance.impedance_ohm

    return Measurement(
        weight_kg=weight.weight_kg,
        impedance_ohm=impedance_ohm,
        display_unit=weight.display_unit,
    )
