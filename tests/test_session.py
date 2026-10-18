"""Measurement session and device data tests using a fake GATT client."""

from __future__ import annotations

import asyncio
from functools import partial
import logging
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch

from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bluetooth_data_tools import monotonic_time_coarse
from habluetooth import BluetoothServiceInfo, BluetoothServiceInfoBleak
import pytest

from vitafit_ble import (
    DisplayUnit,
    Frame,
    Measurement,
    VitafitSession,
    async_measure,
    async_poll,
    device_name,
    poll_needed,
    supported,
)
from vitafit_ble.protocol import (
    ACK_IMPEDANCE,
    ACK_STABLE_WEIGHT,
    ImpedanceFrame,
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
    SETTLING,
    SETTLING_LB,
    SETTLING_ST,
    STABLE,
    STABLE_LB,
    STABLE_ST,
    START_REPLIES,
    UNIT_ACK,
)

KG = DisplayUnit.KG

if TYPE_CHECKING:
    from collections.abc import Callable


START_COMMANDS = tuple(start_commands())
ACK_SETTLING = ack_command(SETTLING)
# Everything the session sends, in order: no unit command, so the scale keeps its
# display unit, and an acknowledgement for every frame, including the stable
# weight the scale repeats while it measures impedance.
FULL_EXCHANGE = [
    *START_COMMANDS,
    ACK_SETTLING,
    ACK_STABLE_WEIGHT,
    ACK_STABLE_WEIGHT,
    ACK_IMPEDANCE,
]
WEIGHT_ONLY_START_COMMANDS = tuple(start_commands(weight_only=True))


class FakeClient:
    """Replies to commands like the VT701 did in the captures (see frames.py)."""

    def __init__(
        self,
        *,
        first: bytes = SETTLING,
        stable: bytes = STABLE,
        send_stable: bool = True,
        impedance: bytes | None = IMPEDANCE,
    ) -> None:
        self.written: list[bytes] = []
        self.first = first
        self.stable = stable
        self.send_stable = send_stable
        self.impedance = impedance
        self._callback: Callable[[Any, bytearray], None] | None = None
        self._measuring_impedance = False
        self.disconnect = AsyncMock()

    async def start_notify(
        self, _: str, callback: Callable[[Any, bytearray], None]
    ) -> None:
        self._callback = callback

    def _notify(self, frame: bytes) -> None:
        assert self._callback is not None
        self._callback(None, bytearray(frame))

    async def write_gatt_char(self, _: str, data: bytes, *, response: bool) -> None:
        assert response
        self.written.append(data)
        if data == WEIGHT_ONLY_START_COMMANDS[0]:
            # Same reply as in normal mode; the impedance frame shows the mode.
            self._notify(START_REPLIES[0])
            self.impedance = IMPEDANCE_WEIGHT_ONLY
        elif data in START_COMMANDS:
            self._notify(START_REPLIES[START_COMMANDS.index(data)])
            if data == START_COMMANDS[-1]:
                self._notify(self.first)
                if self.send_stable:
                    self._notify(self.stable)
        elif data in {unit_command(unit) for unit in DisplayUnit}:
            self._notify(UNIT_ACK)
        elif data == ACK_STABLE_WEIGHT and not self._measuring_impedance:
            # The scale keeps sending the stable weight until impedance is ready.
            self._measuring_impedance = True
            self._notify(self.stable)
            if self.impedance is not None:
                self._notify(self.impedance)


@pytest.mark.parametrize(
    ("first", "stable", "expected"),
    [
        (SETTLING, STABLE, Measurement(87.35, impedance_ohm=466, display_unit=KG)),
        (
            SETTLING_LB,
            STABLE_LB,
            Measurement(87.2, impedance_ohm=466, display_unit=DisplayUnit.LB),
        ),
        (
            SETTLING_ST,
            STABLE_ST,
            Measurement(87.2, impedance_ohm=466, display_unit=DisplayUnit.ST),
        ),
    ],
)
async def test_full_measurement(
    first: bytes, stable: bytes, expected: Measurement
) -> None:
    """Weight is in kg whatever the display unit, and no unit command is sent."""
    client = FakeClient(first=first, stable=stable)
    assert await async_measure(client) == expected  # type: ignore[arg-type]
    assert client.written == FULL_EXCHANGE


async def test_status_logged(caplog: pytest.LogCaptureFixture) -> None:
    """Each stage of the weigh-in is logged at debug level."""
    with caplog.at_level(logging.DEBUG, logger="vitafit_ble.session"):
        await async_measure(FakeClient())  # type: ignore[arg-type]
    messages = [
        record.getMessage()
        for record in caplog.records
        if not record.getMessage().startswith(("Sending", "Received"))
    ]
    assert messages == [
        "Waiting up to 30.0 s for a stable weight",
        f"Weight: {decode(STABLE)}",
        "Waiting up to 10.0 s for impedance",
        f"Impedance: {decode(IMPEDANCE)}",
        f"Result: {Measurement(87.35, 466, KG)}",
    ]
    assert {record.levelno for record in caplog.records} == {logging.DEBUG}


@pytest.mark.parametrize("unit", list(DisplayUnit))
async def test_set_display_unit(unit: DisplayUnit) -> None:
    """The unit command goes after the mode and hello commands.

    The result reports the unit in the stable weight frame, here st.
    """
    client = FakeClient(first=SETTLING_ST, stable=STABLE_ST)
    result = await async_measure(client, VitafitSession(display_unit=unit))  # type: ignore[arg-type]
    assert result == Measurement(87.2, impedance_ohm=466, display_unit=DisplayUnit.ST)
    assert client.written == [
        *START_COMMANDS,
        unit_command(unit),
        ack_command(SETTLING_ST),
        ACK_STABLE_WEIGHT,
        ACK_STABLE_WEIGHT,
        ACK_IMPEDANCE,
    ]


async def test_first_frame_stable() -> None:
    """Stepping on before connecting: the first frame is already stable."""
    client = FakeClient(first=STABLE, send_stable=False)
    result = await async_measure(client)  # type: ignore[arg-type]
    assert result == Measurement(87.35, impedance_ohm=466, display_unit=KG)
    assert client.written == [
        *START_COMMANDS,
        ACK_STABLE_WEIGHT,
        ACK_STABLE_WEIGHT,
        ACK_IMPEDANCE,
    ]


async def test_ack_only_stable_weight_and_impedance() -> None:
    """Without ack_every_frame, only the frames waited for are acknowledged."""
    client = FakeClient()
    result = await async_measure(client, VitafitSession(ack_every_frame=False))  # type: ignore[arg-type]
    assert result == Measurement(87.35, impedance_ohm=466, display_unit=KG)
    assert client.written == [*START_COMMANDS, ACK_STABLE_WEIGHT, ACK_IMPEDANCE]


async def test_corrupt_frame_not_acknowledged() -> None:
    """A frame that fails its checks isn't acknowledged, so the scale resends it."""
    corrupt = SETTLING[:-2] + bytes((SETTLING[-2] ^ 0xFF,)) + SETTLING[-1:]
    client = FakeClient(first=corrupt)
    result = await async_measure(client)  # type: ignore[arg-type]
    assert result == Measurement(87.35, impedance_ohm=466, display_unit=KG)
    assert client.written == [
        *START_COMMANDS,
        ACK_STABLE_WEIGHT,
        ACK_STABLE_WEIGHT,
        ACK_IMPEDANCE,
    ]


class BacklogClient(FakeClient):
    """Sends another frame before each acknowledgement finishes, as a slow link can."""

    async def write_gatt_char(self, uuid: str, data: bytes, *, response: bool) -> None:
        await super().write_gatt_char(uuid, data, response=response)
        if data == ACK_SETTLING:
            self._notify(SETTLING)


async def test_timeout_with_backlog(caplog: pytest.LogCaptureFixture) -> None:
    """The weight timeout still ends the weigh-in while frames are queued."""
    client = BacklogClient(send_stable=False)
    with caplog.at_level(logging.DEBUG, logger="vitafit_ble.session"):
        assert await async_measure(client, VitafitSession(weight_timeout=0.01)) is None  # type: ignore[arg-type]
    assert "No stable weight within 0.01 s" in caplog.text


class BurstClient(FakeClient):
    """Sends several settling frames at once before the stable weight."""

    def __init__(self) -> None:
        super().__init__(send_stable=False)

    async def write_gatt_char(self, uuid: str, data: bytes, *, response: bool) -> None:
        await super().write_gatt_char(uuid, data, response=response)
        if data == START_COMMANDS[-1]:
            for _ in range(4):
                self._notify(SETTLING)
            self._notify(STABLE)


async def test_optional_acks_skipped_while_one_waits() -> None:
    """Frames that arrive faster than acks are sent don't build up a backlog.

    Only the first settling frame's ack is queued; the stable weight's and the
    impedance's acks are never skipped.
    """
    client = BurstClient()
    result = await async_measure(client)  # type: ignore[arg-type]
    assert result == Measurement(87.35, impedance_ohm=466, display_unit=KG)
    assert client.written == FULL_EXCHANGE


async def test_impedance_before_stable_weight(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An impedance frame ends the weigh-in, even before a stable weight."""
    client = FakeClient(first=IMPEDANCE, send_stable=False)
    with caplog.at_level(logging.DEBUG, logger="vitafit_ble.session"):
        result = await async_measure(client, VitafitSession(weight_timeout=5))  # type: ignore[arg-type]
    assert result is None
    # Acknowledged so the scale stops repeating it; nothing after it is.
    assert client.written == [*START_COMMANDS, ACK_IMPEDANCE]
    assert "Impedance before a stable weight ends the weigh-in" in caplog.text
    assert "No stable weight within" not in caplog.text


async def test_impedance_failed() -> None:
    """In socks, the scale reports a failed impedance; return at once without it."""
    client = FakeClient(impedance=IMPEDANCE_FAILED)
    result = await async_measure(client, VitafitSession(impedance_timeout=1))  # type: ignore[arg-type]
    assert result == Measurement(87.35, impedance_ohm=None, display_unit=KG)
    assert client.written == FULL_EXCHANGE


async def test_weight_only() -> None:
    """Weight-only mode: the mode command selects it, and the scale skips impedance."""
    client = FakeClient()
    result = await async_measure(client, VitafitSession(weight_only=True))  # type: ignore[arg-type]
    assert result == Measurement(87.35, impedance_ohm=None, display_unit=KG)
    assert client.written == [
        *WEIGHT_ONLY_START_COMMANDS,
        ACK_SETTLING,
        ACK_STABLE_WEIGHT,
        ACK_STABLE_WEIGHT,
        ACK_IMPEDANCE,
    ]


async def test_stepped_off_early(caplog: pytest.LogCaptureFixture) -> None:
    """Stepping off early: no impedance frame arrives."""
    client = FakeClient(impedance=None)
    with caplog.at_level(logging.DEBUG, logger="vitafit_ble.session"):
        result = await async_measure(client, VitafitSession(impedance_timeout=0.01))  # type: ignore[arg-type]
    assert result == Measurement(87.35, impedance_ohm=None, display_unit=KG)
    assert ACK_IMPEDANCE not in client.written
    assert "No impedance within 0.01 s" in caplog.text


async def test_no_stable_weight(caplog: pytest.LogCaptureFixture) -> None:
    client = FakeClient(send_stable=False)
    with caplog.at_level(logging.DEBUG, logger="vitafit_ble.session"):
        assert await async_measure(client, VitafitSession(weight_timeout=0.01)) is None  # type: ignore[arg-type]
    assert ACK_STABLE_WEIGHT not in client.written
    assert "No stable weight within 0.01 s" in caplog.text


class HookSession(VitafitSession):
    """Record every raw hook and frame callback."""

    def __init__(self, *, weight_only: bool = False) -> None:
        super().__init__(weight_only=weight_only)
        self.events: list[tuple[str, object]] = []
        self.register_callback(WeightFrame, partial(self._record, "weight"))
        self.register_callback(ImpedanceFrame, partial(self._record, "impedance"))
        self.register_callback(Frame, partial(self._record, "frame"))

    def on_send(self, data: bytes) -> None:
        self.events.append(("send", data))

    def on_receive(self, data: bytes) -> None:
        self.events.append(("receive", data))

    def _record(self, kind: str, frame: Frame) -> None:
        self.events.append((kind, frame))


def _callbacks(data: bytes) -> list[tuple[str, object]]:
    """Return the callback calls for one decoded frame."""
    frame = decode(data)
    assert frame is not None
    # In the order HookSession registers them.
    kind = "weight" if isinstance(frame, WeightFrame) else "impedance"
    return [(kind, frame), ("frame", frame)]


async def test_async_measure_session() -> None:
    """The session's options and callbacks are used for the weigh-in."""
    client = FakeClient()
    session = HookSession(weight_only=True)
    result = await async_measure(client, session)  # type: ignore[arg-type]
    assert result == Measurement(87.35, impedance_ohm=None, display_unit=KG)
    assert client.written[0] == WEIGHT_ONLY_START_COMMANDS[0]
    assert ("weight", decode(SETTLING)) in session.events


async def test_session_hooks() -> None:
    """The raw hooks see every frame as it arrives, including late ones.

    The callbacks see each frame as the weigh-in takes it, before its
    acknowledgement, which is sent in order in the background.
    """
    client = FakeClient()
    session = HookSession()
    result = await session.async_measure(client)  # type: ignore[arg-type]
    assert result == Measurement(87.35, impedance_ohm=466, display_unit=KG)
    mode, hello = START_COMMANDS
    assert session.events == [
        ("send", mode),
        ("receive", START_REPLIES[0]),
        ("send", hello),
        ("receive", START_REPLIES[1]),
        ("receive", SETTLING),
        ("receive", STABLE),
        *_callbacks(SETTLING),
        *_callbacks(STABLE),
        # Sent while the weigh-in waits for the next frame.
        ("send", ACK_SETTLING),
        # The scale replies to the stable weight's acknowledgement at once.
        ("send", ACK_STABLE_WEIGHT),
        ("receive", STABLE),
        ("receive", IMPEDANCE),
        *_callbacks(STABLE),
        *_callbacks(IMPEDANCE),
        # Sent before async_measure returns.
        ("send", ACK_STABLE_WEIGHT),
        ("send", ACK_IMPEDANCE),
    ]

    # Notifications after the weigh-in still reach the raw hook only.
    session.events.clear()
    client._notify(STABLE)
    assert session.events == [("receive", STABLE)]


async def test_multiple_callbacks() -> None:
    """A frame's callbacks run in the order registered, whatever their type."""
    calls: list[tuple[str, Frame]] = []
    session = VitafitSession()
    session.register_callback(Frame, partial(_append, calls, "first"))
    session.register_callback(WeightFrame, partial(_append, calls, "second"))
    session.register_callback(Frame, partial(_append, calls, "third"))
    await async_measure(FakeClient(), session)  # type: ignore[arg-type]
    settling = decode(SETTLING)
    assert calls[:3] == [
        ("first", settling),
        ("second", settling),
        ("third", settling),
    ]


def _append(calls: list[tuple[str, Frame]], name: str, frame: Frame) -> None:
    calls.append((name, frame))


class CallbackError(Exception):
    """Raised by a test callback."""


async def test_callback_exception_ends_weigh_in() -> None:
    """An exception from a callback is raised by async_measure."""
    session = VitafitSession()

    def _fail(_: WeightFrame) -> None:
        raise CallbackError

    session.register_callback(WeightFrame, _fail)
    client = FakeClient()
    with pytest.raises(CallbackError):
        await session.async_measure(client)  # type: ignore[arg-type]
    # It ended at the first frame, before its queued acknowledgement was sent.
    assert client.written == list(START_COMMANDS)


class FailingAckClient(FakeClient):
    """Fails the first acknowledgement, then sends another frame if ``stream``."""

    def __init__(self, *, stream: bool) -> None:
        super().__init__(send_stable=False)
        self.stream = stream

    async def write_gatt_char(self, uuid: str, data: bytes, *, response: bool) -> None:
        if data == ACK_SETTLING:
            if self.stream:
                self._notify(SETTLING)
            msg = "write failed"
            raise BleakError(msg)
        await super().write_gatt_char(uuid, data, response=response)


async def test_ack_error_raised_at_next_frame() -> None:
    """A failed acknowledgement's error is raised at the next frame."""
    client = FailingAckClient(stream=True)
    session = VitafitSession(weight_timeout=5, impedance_timeout=5)
    loop = asyncio.get_running_loop()
    start = loop.time()
    with pytest.raises(BleakError, match="write failed"):
        await session.async_measure(client)  # type: ignore[arg-type]
    # Long before the timeout, so not from waiting for the sender at the end.
    assert loop.time() - start < 1


async def test_ack_error_raised_at_timeout() -> None:
    """With no more frames, a failed acknowledgement's error ends the weigh-in."""
    client = FailingAckClient(stream=False)
    session = VitafitSession(weight_timeout=0.1)
    with pytest.raises(BleakError, match="write failed"):
        await session.async_measure(client)  # type: ignore[arg-type]


class SlowAckClient(FakeClient):
    """Sends another frame during the first acknowledgement, which never finishes."""

    def __init__(self) -> None:
        super().__init__(send_stable=False)
        self.ack_cancelled = False

    async def write_gatt_char(self, uuid: str, data: bytes, *, response: bool) -> None:
        if data != ACK_SETTLING:
            await super().write_gatt_char(uuid, data, response=response)
            return
        self._notify(SETTLING)
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            self.ack_cancelled = True
            raise


async def test_sender_stopped_before_return() -> None:
    """An acknowledgement still being written is stopped before async_measure ends.

    So the caller doesn't disconnect while it's still running.
    """
    session = VitafitSession()
    calls: list[WeightFrame] = []

    def _fail_second(frame: WeightFrame) -> None:
        calls.append(frame)
        if len(calls) == 2:
            raise CallbackError

    session.register_callback(WeightFrame, _fail_second)
    client = SlowAckClient()
    with pytest.raises(CallbackError):
        await session.async_measure(client)  # type: ignore[arg-type]
    assert client.ack_cancelled


async def test_unregister_callback() -> None:
    weights: list[WeightFrame] = []
    session = VitafitSession()
    unregister = session.register_callback(WeightFrame, weights.append)
    unregister()
    await async_measure(FakeClient(), session)  # type: ignore[arg-type]
    assert weights == []


def service_info(name: str) -> BluetoothServiceInfo:
    return BluetoothServiceInfo(
        name=name,
        address="AA:BB:CC:DD:EE:FF",
        rssi=-60,
        manufacturer_data={},
        service_data={},
        service_uuids=[],
        source="local",
    )


def test_supported() -> None:
    assert supported(service_info("Vitafit Body Fat"))
    assert not supported(service_info("Other"))


def test_device_name() -> None:
    assert device_name("AA:BB:CC:DD:EE:FF") == "Vitafit VT701 EEFF"


def bleak_service_info(age: float) -> BluetoothServiceInfoBleak:
    """Return an advertisement received ``age`` seconds ago."""
    return BluetoothServiceInfoBleak(
        name="Vitafit Body Fat",
        address="AA:BB:CC:DD:EE:FF",
        rssi=-60,
        manufacturer_data={},
        service_data={},
        service_uuids=[],
        source="local",
        device=BLEDevice("AA:BB:CC:DD:EE:FF", "Vitafit Body Fat", None),
        advertisement=None,
        connectable=True,
        time=monotonic_time_coarse() - age,
        tx_power=None,
    )


def test_poll_needed() -> None:
    info = bleak_service_info(0)
    assert poll_needed(info, None)
    assert not poll_needed(info, 10)
    assert poll_needed(info, 61)


def test_poll_needed_stale_advertisement() -> None:
    info = bleak_service_info(10)
    assert not poll_needed(info, None)
    assert not poll_needed(info, 61)


BLE_DEVICE = BLEDevice("AA:BB:CC:DD:EE:FF", "Vitafit Body Fat", None)


async def test_async_poll() -> None:
    client = FakeClient()
    with patch(
        "vitafit_ble.device.establish_connection", AsyncMock(return_value=client)
    ):
        measurement = await async_poll(BLE_DEVICE)
    client.disconnect.assert_awaited_once()
    assert measurement == Measurement(87.35, impedance_ohm=466, display_unit=KG)


async def test_async_poll_session() -> None:
    """The session's options and callbacks are used for the weigh-in."""
    weights: list[WeightFrame] = []
    session = VitafitSession(weight_only=True)
    session.register_callback(WeightFrame, weights.append)
    client = FakeClient()
    with patch(
        "vitafit_ble.device.establish_connection", AsyncMock(return_value=client)
    ):
        measurement = await async_poll(BLE_DEVICE, session)
    assert client.written[0] == WEIGHT_ONLY_START_COMMANDS[0]
    assert measurement == Measurement(87.35, impedance_ohm=None, display_unit=KG)
    assert weights[0] == decode(SETTLING)


async def test_async_poll_bleak_error(caplog: pytest.LogCaptureFixture) -> None:
    """A Bluetooth error during the weigh-in is raised, after disconnecting."""
    client = FakeClient()
    client.start_notify = AsyncMock(side_effect=BleakError("disconnected"))  # type: ignore[method-assign]
    with (
        patch(
            "vitafit_ble.device.establish_connection", AsyncMock(return_value=client)
        ),
        pytest.raises(BleakError, match="disconnected"),
    ):
        await async_poll(BLE_DEVICE)
    client.disconnect.assert_awaited_once()
    # Not logged, so the caller can log a run of failures once.
    assert not [record for record in caplog.records if record.levelno > logging.DEBUG]
