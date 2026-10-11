"""Measurement session over an open GATT connection."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from typing import TYPE_CHECKING, TypeVar, cast

from .const import (
    IMPEDANCE_TIMEOUT,
    NOTIFY_CHARACTERISTIC_UUID,
    WEIGHT_TIMEOUT,
    WRITE_CHARACTERISTIC_UUID,
)
from .protocol import (
    ACK_IMPEDANCE,
    ACK_STABLE_WEIGHT,
    Frame,
    ImpedanceFrame,
    WeightFrame,
    decode,
    start_commands,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from bleak import BleakClient
    from bleak.backends.characteristic import BleakGATTCharacteristic

    from .protocol import DisplayUnit

_LOGGER = logging.getLogger(__name__)

_FrameT = TypeVar("_FrameT", bound=Frame)


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


class VitafitSession:
    """The options and callbacks for one weigh-in.

    ``async_measure`` runs the exchange on a connected client. Register
    callbacks for decoded frames with ``register_callback``, for example to show
    the live weight, and subclass to override ``on_send`` and ``on_receive`` for
    the raw bytes, for example to log the exchange. They only observe; they
    don't change the exchange. The receive callbacks run as each notification
    arrives, including any after ``async_measure`` returns, until the client
    disconnects.

    Create one per weigh-in. It can be reused for later weigh-ins, but not
    while one is running.
    """

    def __init__(
        self,
        *,
        weight_timeout: float = WEIGHT_TIMEOUT,
        impedance_timeout: float = IMPEDANCE_TIMEOUT,
        display_unit: DisplayUnit | None = None,
        weight_only: bool = False,
    ) -> None:
        """Set the weigh-in options.

        Wait up to ``weight_timeout`` seconds for a stable weight, then up to
        ``impedance_timeout`` for impedance.

        With ``display_unit``, set the scale's display unit after the mode and
        hello commands. Without it, the scale keeps its display unit. The
        weight is always in kg.

        With ``weight_only``, select the scale's weight-only mode, which passes
        no current, so impedance is None. Without it, select the normal mode.
        The scale keeps the mode for later weigh-ins without a connection.
        """
        self._weight_timeout = weight_timeout
        self._impedance_timeout = impedance_timeout
        self._display_unit = display_unit
        self._weight_only = weight_only
        self._callbacks: dict[type[Frame], list[Callable[[Frame], None]]] = {}
        self._frames: asyncio.Queue[Frame] = asyncio.Queue()

    def register_callback(
        self, frame_type: type[_FrameT], callback: Callable[[_FrameT], None]
    ) -> Callable[[], None]:
        """Call ``callback`` with each decoded frame of ``frame_type``.

        ``frame_type`` is ``WeightFrame`` (streamed about every 0.36 s),
        ``ImpedanceFrame`` (before it's acknowledged), or ``Frame`` for both.
        Callbacks for a frame's own class run before those for ``Frame``, each
        in the order registered. Return a function that unregisters it.
        """
        callbacks = self._callbacks.setdefault(frame_type, [])
        frame_callback = cast("Callable[[Frame], None]", callback)
        callbacks.append(frame_callback)

        def _unregister() -> None:
            callbacks.remove(frame_callback)

        return _unregister

    def on_send(self, data: bytes) -> None:
        """Handle a command's raw bytes, just before they're written."""

    def on_receive(self, data: bytes) -> None:
        """Handle a notification's raw bytes, including command replies.

        Called before the callbacks for its decoded frame.
        """

    async def async_measure(self, client: BleakClient) -> Measurement | None:
        """Run the weigh-in on a connected ``client``.

        Return None if no stable weight arrives in time. Impedance is None if
        the scale can't measure it, for example through socks, or doesn't
        report it in time, for example when the user steps off early.
        """
        self._frames = asyncio.Queue()
        await client.start_notify(NOTIFY_CHARACTERISTIC_UUID, self._on_notify)
        for command in start_commands(
            weight_only=self._weight_only, display_unit=self._display_unit
        ):
            await self._async_write(client, command)

        try:
            async with asyncio.timeout(self._weight_timeout):
                weight = await self._async_stable_weight()
        except TimeoutError:
            _LOGGER.debug("No stable weight within %s s", self._weight_timeout)
            return None
        else:
            # openScale says acknowledging the stable weight starts the impedance
            # measurement. Untested: no normal-mode weigh-in has skipped it.
            await self._async_write(client, ACK_STABLE_WEIGHT)

        try:
            async with asyncio.timeout(self._impedance_timeout):
                impedance = await self._async_impedance()
        except TimeoutError:
            _LOGGER.debug(
                "No impedance within %s s; returning weight only",
                self._impedance_timeout,
            )
            impedance_ohm = None
        else:
            await self._async_write(client, ACK_IMPEDANCE)
            impedance_ohm = impedance.impedance_ohm

        return Measurement(
            weight_kg=weight.weight_kg,
            impedance_ohm=impedance_ohm,
            display_unit=weight.display_unit,
        )

    def _on_notify(self, _: BleakGATTCharacteristic, data: bytearray) -> None:
        received = bytes(data)
        frame = decode(received)
        _LOGGER.debug("Received %s: %s", received.hex(" "), frame)
        self.on_receive(received)
        if frame is None:
            return
        for frame_type in type(frame).__mro__:
            for callback in list(self._callbacks.get(frame_type, ())):
                callback(frame)
        self._frames.put_nowait(frame)

    async def _async_write(self, client: BleakClient, command: bytes) -> None:
        _LOGGER.debug("Sending %s", command.hex(" "))
        self.on_send(command)
        await client.write_gatt_char(WRITE_CHARACTERISTIC_UUID, command, response=True)

    async def _async_stable_weight(self) -> WeightFrame:
        while True:
            frame = await self._frames.get()
            if isinstance(frame, WeightFrame) and frame.stable:
                return frame

    async def _async_impedance(self) -> ImpedanceFrame:
        while True:
            frame = await self._frames.get()
            if isinstance(frame, ImpedanceFrame):
                return frame


async def async_measure(
    client: BleakClient, session: VitafitSession | None = None
) -> Measurement | None:
    """Run one weigh-in on a connected client.

    ``session`` sets the options and callbacks; by default a ``VitafitSession()``.
    For example ``await async_measure(client, VitafitSession(weight_only=True))``.

    Return None if no stable weight arrives in time.
    """
    if session is None:
        session = VitafitSession()
    return await session.async_measure(client)
