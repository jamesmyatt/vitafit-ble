"""Measurement session over an open GATT connection."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from typing import TYPE_CHECKING, cast

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
    don't change the exchange. ``on_receive`` runs as each notification
    arrives, including any after ``async_measure`` returns, until the client
    disconnects. The frame callbacks run in ``async_measure`` as it takes
    each frame, so they stop when it returns, and an exception from one ends
    the weigh-in. Acknowledgements are sent in order in the background, so
    they don't hold up the callbacks.

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

        With ``ack_every_frame``, the default, also acknowledge each settling
        and stable weight frame, as the Vitafit app does, so that the scale
        can replace any frame that went missing or failed its checks. No-load
        frames and unknown flags aren't acknowledged, and while an ack is
        already waiting to be sent, the extra ones are skipped, so a slow link
        can't build up a backlog. The first stable weight's and the
        impedance's acks are never skipped. Without it, only acknowledge the
        first stable weight and the impedance, as openScale does.
        """
        self._weight_timeout = weight_timeout
        self._impedance_timeout = impedance_timeout
        self._display_unit = display_unit
        self._weight_only = weight_only
        self._ack_every_frame = ack_every_frame
        self._callbacks: tuple[tuple[type[Frame], Callable[[Frame], None]], ...] = ()
        self._frames: asyncio.Queue[WeightFrame | ImpedanceFrame] = asyncio.Queue()
        self._weight: WeightFrame | None = None
        self._impedance: ImpedanceFrame | None = None

    def register_callback[FrameT: Frame](
        self, frame_type: type[FrameT], callback: Callable[[FrameT], None]
    ) -> Callable[[], None]:
        """Call ``callback`` with each decoded frame of ``frame_type``.

        ``frame_type`` is ``WeightFrame`` (streamed about every 0.36 s),
        ``ImpedanceFrame``, or ``Frame`` for both. Callbacks run during
        ``async_measure``, before the frame's acknowledgement is sent. A frame's
        callbacks run in the order registered, whatever their ``frame_type``.
        An exception from a callback ends the weigh-in: ``async_measure``
        raises it. Return a function that unregisters it.
        """
        registration = (frame_type, cast("Callable[[Frame], None]", callback))
        self._callbacks = (*self._callbacks, registration)

        def _unregister() -> None:
            callbacks = list(self._callbacks)
            callbacks.remove(registration)
            self._callbacks = tuple(callbacks)

        return _unregister

    def on_send(self, data: bytes) -> None:
        """Handle a command's raw bytes, just before they're written."""

    def on_receive(self, data: bytes) -> None:
        """Handle a notification's raw bytes, including command replies.

        Called before the callbacks for its decoded frame.
        """

    async def async_measure(self, client: BleakClient) -> Measurement | None:
        """Run the weigh-in on a connected ``client``.

        Return None if no stable weight arrives in time, or if the impedance
        arrives first, since that ends the weigh-in. Impedance is None if
        the scale can't measure it, for example through socks, or doesn't
        report it in time, for example when the user steps off early.
        """
        await self._async_start(client)
        # A separate task sends the acks, in order, so they don't hold up the
        # callbacks. None stops it.
        acks: asyncio.Queue[bytes | None] = asyncio.Queue()
        sender = asyncio.create_task(self._async_send_acks(client, acks))
        try:
            await self._async_take_frames(acks, sender)
            acks.put_nowait(None)
            await sender  # Sends the acks still queued; raises a write's error.
        finally:
            sender.cancel()
            await asyncio.wait({sender})
        measurement = self._measurement()
        _LOGGER.debug("Result: %s", measurement)
        return measurement

    async def _async_take_frames(
        self, acks: asyncio.Queue[bytes | None], sender: asyncio.Task[None]
    ) -> None:
        loop = asyncio.get_running_loop()
        # Only taking a frame is timed; the sender task does the writes.
        deadline = loop.time() + self._weight_timeout
        _LOGGER.debug("Waiting up to %s s for a stable weight", self._weight_timeout)
        while self._impedance is None:
            if sender.done():
                sender.result()  # It only stops early if a write failed.
            try:
                frame = await self._async_next_frame(deadline)
            except TimeoutError:
                if self._weight is None:
                    _LOGGER.debug("No stable weight within %s s", self._weight_timeout)
                else:
                    _LOGGER.debug(
                        "No impedance within %s s; returning weight only",
                        self._impedance_timeout,
                    )
                return

            # openScale says acknowledging the stable weight starts the
            # impedance measurement. Untested: no normal-mode weigh-in has
            # skipped it. The impedance ends the weigh-in whenever it arrives.
            wanted = isinstance(frame, ImpedanceFrame) or (
                self._weight is None and frame.stable
            )
            # Optional acks are skipped while one is already waiting to be
            # sent, so a slow link can't build up a backlog. ack_command gives
            # None for a weight flag that isn't acknowledged.
            if (wanted or (self._ack_every_frame and acks.empty())) and (
                ack := ack_command(frame)
            ) is not None:
                acks.put_nowait(ack)
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
            else:
                self._impedance = frame
                _LOGGER.debug("Impedance: %s", frame)
                if self._weight is None:
                    _LOGGER.debug("Impedance before a stable weight ends the weigh-in")

    async def _async_send_acks(
        self, client: BleakClient, acks: asyncio.Queue[bytes | None]
    ) -> None:
        while (ack := await acks.get()) is not None:
            await self._async_write(client, ack)

    async def _async_next_frame(self, deadline: float) -> WeightFrame | ImpedanceFrame:
        """Take the next frame; raise TimeoutError once ``deadline`` has passed."""
        # Checked first: get() doesn't wait while frames are queued, so the
        # timeout can't fire then.
        if asyncio.get_running_loop().time() >= deadline:
            raise TimeoutError
        async with asyncio.timeout_at(deadline):
            return await self._frames.get()

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
        for frame_type, callback in self._callbacks:
            if isinstance(frame, frame_type):
                callback(frame)

    def _on_notify(self, _: BleakGATTCharacteristic, data: bytearray) -> None:
        received = bytes(data)
        frame = decode(received)
        _LOGGER.debug("Received %s: %s", received.hex(" "), frame)
        self.on_receive(received)
        if frame is not None:
            self._frames.put_nowait(frame)

    async def _async_write(self, client: BleakClient, command: bytes) -> None:
        _LOGGER.debug("Sending %s", command.hex(" "))
        self.on_send(command)
        await client.write_gatt_char(WRITE_CHARACTERISTIC_UUID, command, response=True)

    def _measurement(self) -> Measurement | None:
        if self._weight is None:
            return None
        return Measurement(
            weight_kg=self._weight.weight_kg,
            impedance_ohm=(
                self._impedance.impedance_ohm if self._impedance is not None else None
            ),
            display_unit=self._weight.display_unit,
        )


async def async_measure(
    client: BleakClient, session: VitafitSession | None = None
) -> Measurement | None:
    """Run one weigh-in on a connected client.

    ``session`` sets the options and callbacks; by default a ``VitafitSession()``.
    For example ``await async_measure(client, VitafitSession(weight_only=True))``.

    Return None if no stable weight arrives in time, or if the impedance
    arrives first.
    """
    if session is None:
        session = VitafitSession()
    return await session.async_measure(client)
