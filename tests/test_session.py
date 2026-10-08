"""Measurement session and device data tests using a fake GATT client."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch

from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bluetooth_data_tools import monotonic_time_coarse
from habluetooth import BluetoothServiceInfo, BluetoothServiceInfoBleak
import pytest
from sensor_state_data import DeviceKey

from vitafit_ble import (
    DisplayUnit,
    Measurement,
    VitafitBluetoothDeviceData,
    async_measure,
)
from vitafit_ble.protocol import (
    ACK_IMPEDANCE,
    ACK_STABLE_WEIGHT,
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
# Everything the session sends, in order: no unit command, so the scale keeps its
# display unit.
FULL_EXCHANGE = [*START_COMMANDS, ACK_STABLE_WEIGHT, ACK_IMPEDANCE]
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
        elif data == ACK_STABLE_WEIGHT:
            # The scale keeps sending the stable weight until impedance is ready.
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


@pytest.mark.parametrize("unit", list(DisplayUnit))
async def test_set_display_unit(unit: DisplayUnit) -> None:
    """The unit command goes after the mode and hello commands.

    The result reports the unit in the stable weight frame, here st.
    """
    client = FakeClient(first=SETTLING_ST, stable=STABLE_ST)
    result = await async_measure(client, display_unit=unit)  # type: ignore[arg-type]
    assert result == Measurement(87.2, impedance_ohm=466, display_unit=DisplayUnit.ST)
    assert client.written == [
        *START_COMMANDS,
        unit_command(unit),
        ACK_STABLE_WEIGHT,
        ACK_IMPEDANCE,
    ]


async def test_first_frame_stable() -> None:
    """Stepping on before connecting: the first frame is already stable."""
    client = FakeClient(first=STABLE, send_stable=False)
    result = await async_measure(client)  # type: ignore[arg-type]
    assert result == Measurement(87.35, impedance_ohm=466, display_unit=KG)
    assert client.written == FULL_EXCHANGE


async def test_impedance_failed() -> None:
    """In socks, the scale reports a failed impedance; return at once without it."""
    client = FakeClient(impedance=IMPEDANCE_FAILED)
    result = await async_measure(client, impedance_timeout=1)  # type: ignore[arg-type]
    assert result == Measurement(87.35, impedance_ohm=None, display_unit=KG)
    assert client.written == FULL_EXCHANGE


async def test_weight_only() -> None:
    """Weight-only mode: the mode command selects it, and the scale skips impedance."""
    client = FakeClient()
    result = await async_measure(client, weight_only=True)  # type: ignore[arg-type]
    assert result == Measurement(87.35, impedance_ohm=None, display_unit=KG)
    assert client.written == [
        *WEIGHT_ONLY_START_COMMANDS,
        ACK_STABLE_WEIGHT,
        ACK_IMPEDANCE,
    ]


async def test_stepped_off_early(caplog: pytest.LogCaptureFixture) -> None:
    """Stepping off early: no impedance frame arrives."""
    client = FakeClient(impedance=None)
    with caplog.at_level(logging.DEBUG, logger="vitafit_ble.session"):
        result = await async_measure(client, impedance_timeout=0.01)  # type: ignore[arg-type]
    assert result == Measurement(87.35, impedance_ohm=None, display_unit=KG)
    assert ACK_IMPEDANCE not in client.written
    assert "No impedance within 0.01 s" in caplog.text


async def test_no_stable_weight(caplog: pytest.LogCaptureFixture) -> None:
    client = FakeClient(send_stable=False)
    with caplog.at_level(logging.DEBUG, logger="vitafit_ble.session"):
        assert await async_measure(client, weight_timeout=0.01) is None  # type: ignore[arg-type]
    assert ACK_STABLE_WEIGHT not in client.written
    assert "No stable weight within 0.01 s" in caplog.text


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
    data = VitafitBluetoothDeviceData()
    assert data.supported(service_info("Vitafit Body Fat"))
    assert data.title == "Vitafit VT701 EEFF"
    assert not VitafitBluetoothDeviceData().supported(service_info("Other"))


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
    data = VitafitBluetoothDeviceData()
    info = bleak_service_info(0)
    assert data.poll_needed(info, None)
    assert not data.poll_needed(info, 10)
    assert data.poll_needed(info, 61)


def test_poll_needed_stale_advertisement() -> None:
    data = VitafitBluetoothDeviceData()
    info = bleak_service_info(10)
    assert not data.poll_needed(info, None)
    assert not data.poll_needed(info, 61)


async def test_async_poll() -> None:
    data = VitafitBluetoothDeviceData()
    data.update(service_info("Vitafit Body Fat"))
    client = FakeClient()
    device = BLEDevice("AA:BB:CC:DD:EE:FF", "Vitafit Body Fat", None)
    with patch(
        "vitafit_ble.parser.establish_connection", AsyncMock(return_value=client)
    ):
        update = await data.async_poll(device)
    client.disconnect.assert_awaited_once()
    assert update.entity_values[DeviceKey("mass")].native_value == 87.35
    assert update.entity_values[DeviceKey("impedance")].native_value == 466


async def test_async_poll_weight_only() -> None:
    """Options are passed to async_measure."""
    data = VitafitBluetoothDeviceData()
    data.update(service_info("Vitafit Body Fat"))
    client = FakeClient()
    device = BLEDevice("AA:BB:CC:DD:EE:FF", "Vitafit Body Fat", None)
    with patch(
        "vitafit_ble.parser.establish_connection", AsyncMock(return_value=client)
    ):
        update = await data.async_poll(device, weight_only=True)
    assert client.written[0] == WEIGHT_ONLY_START_COMMANDS[0]
    assert update.entity_values[DeviceKey("mass")].native_value == 87.35
    assert update.entity_values[DeviceKey("impedance")].native_value is None


async def test_async_poll_bleak_error() -> None:
    data = VitafitBluetoothDeviceData()
    data.update(service_info("Vitafit Body Fat"))
    client = FakeClient()
    client.start_notify = AsyncMock(side_effect=BleakError("disconnected"))  # type: ignore[method-assign]
    device = BLEDevice("AA:BB:CC:DD:EE:FF", "Vitafit Body Fat", None)
    with patch(
        "vitafit_ble.parser.establish_connection", AsyncMock(return_value=client)
    ):
        update = await data.async_poll(device)
    client.disconnect.assert_awaited_once()
    assert DeviceKey("mass") not in update.entity_values
