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
    Frame,
    ImpedanceFrame,
    WeightFrame,
    ack_command,
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

    weight_kg: float | None = None
    """Stable weight in kg, to 0.01 kg."""
    impedance_ohm: int | None = None
    """Whole-body impedance in Ω.

    None if the scale couldn't measure it, for example through socks, or didn't
    report it in time, for example when the user stepped off early.
    """
    display_unit: DisplayUnit | None = None
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
    don't change the exchange. ``on_receive`` runs as each notification
    arrives, including any after ``async_measure`` returns, until the client
    disconnects. The frame callbacks run in ``async_measure``, after the
    frame is acknowledged, so they stop when it returns.

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
        ack_every_frame: bool = True,
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

        With ``ack_every_frame``, the default, acknowledge every weight and
        impedance frame, as the Vitafit app does, so that the scale replaces
        any frame that went missing or failed its checks. Without it, only
        acknowledge the stable weight and the impedance, as openScale does.
        """
        self._weight_timeout = weight_timeout
        self._impedance_timeout = impedance_timeout
        self._display_unit = display_unit
        self._weight_only = weight_only
        self._ack_every_frame = ack_every_frame
        self._callbacks: list[tuple[type[Frame], Callable[[Frame], None]]] = []
        self._frames: asyncio.Queue[tuple[Frame, bytes]] = asyncio.Queue()
        self._weight: WeightFrame | None = None
        self._impedance: ImpedanceFrame | None = None

    def register_callback(
        self, frame_type: type[_FrameT], callback: Callable[[_FrameT], None]
    ) -> Callable[[], None]:
        """Call ``callback`` with each decoded frame of ``frame_type``.

        ``frame_type`` is ``WeightFrame`` (streamed about every 0.36 s),
        ``ImpedanceFrame``, or ``Frame`` for both. Callbacks run during
        ``async_measure``, after the frame is acknowledged (with
        ``ack_every_frame``, or if it's the stable weight or the impedance).
        A frame's callbacks run in the order registered, whatever their
        ``frame_type``. Return a function that unregisters it.
        """
        registration = (frame_type, cast("Callable[[Frame], None]", callback))
        self._callbacks.append(registration)

        def _unregister() -> None:
            self._callbacks.remove(registration)

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
        await self._async_start(client)
        loop = asyncio.get_running_loop()
        # Only taking a frame is timed, so a timeout can't interrupt a write.
        deadline = loop.time() + self._weight_timeout
        _LOGGER.debug("Waiting up to %s s for a stable weight", self._weight_timeout)
        while self._impedance is None:
            try:
                async with asyncio.timeout_at(deadline):
                    frame, data = await self._frames.get()
            except TimeoutError:
                if self._weight is None:
                    _LOGGER.debug("No stable weight within %s s", self._weight_timeout)
                else:
                    _LOGGER.debug(
                        "No impedance within %s s; returning weight only",
                        self._impedance_timeout,
                    )
                break

            if self._weight is None:
                # openScale says acknowledging the stable weight starts the
                # impedance measurement. Untested: no normal-mode weigh-in has
                # skipped it.
                wanted = isinstance(frame, WeightFrame) and frame.stable
            else:
                wanted = isinstance(frame, ImpedanceFrame)
            if wanted or self._ack_every_frame:
                await self._async_write(client, ack_command(data))
            self._dispatch(frame)

            if not wanted:
                continue
            if isinstance(frame, WeightFrame):
                self._weight = frame
                deadline = loop.time() + self._impedance_timeout
                _LOGGER.debug("Weight: %s", frame)
                _LOGGER.debug(
                    "Waiting up to %s s for impedance", self._impedance_timeout
                )
            elif isinstance(frame, ImpedanceFrame):
                self._impedance = frame
                _LOGGER.debug("Impedance: %s", frame)

        measurement = self._measurement()
        _LOGGER.debug("Result: %s", measurement)
        return measurement

    async def _async_start(self, client: BleakClient) -> None:
        self._frames = asyncio.Queue()
        self._weight = None
        self._impedance = None
        await client.start_notify(NOTIFY_CHARACTERISTIC_UUID, self._on_notify)
        for command in start_commands(
            weight_only=self._weight_only, display_unit=self._display_unit
        ):
            await self._async_write(client, command)

    def _dispatch(self, frame: Frame) -> None:
        for frame_type, callback in list(self._callbacks):
            if isinstance(frame, frame_type):
                callback(frame)

    def _on_notify(self, _: BleakGATTCharacteristic, data: bytearray) -> None:
        received = bytes(data)
        frame = decode(received)
        _LOGGER.debug("Received %s: %s", received.hex(" "), frame)
        self.on_receive(received)
        if frame is not None:
            self._frames.put_nowait((frame, received))

    async def _async_write(self, client: BleakClient, command: bytes) -> None:
        _LOGGER.debug("Sending %s", command.hex(" "))
        self.on_send(command)
        await client.write_gatt_char(WRITE_CHARACTERISTIC_UUID, command, response=True)

    def _measurement(self) -> Measurement | None:
        if self._weight is None:
            return None
        return Measurement(
            weight_kg=self._weight.weight_kg,
            impedance_ohm=self._impedance.impedance_ohm if self._impedance else None,
            display_unit=self._weight.display_unit,
        )


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
