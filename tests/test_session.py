"""Measurement session and device data tests using a fake GATT client."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch

from bleak.backends.device import BLEDevice
from home_assistant_bluetooth import BluetoothServiceInfo
from sensor_state_data import DeviceKey

from vitafit_ble import Measurement, VitafitBluetoothDeviceData, async_measure
from vitafit_ble.protocol import ACK_IMPEDANCE, ACK_STABLE_WEIGHT, HELLO_COMMANDS

if TYPE_CHECKING:
    from collections.abc import Callable

SETTLING = bytes.fromhex("5a 0a 26 10 01 00 00 21 21 43 7e aa")
STABLE = bytes.fromhex("5a 0a 26 10 02 00 00 21 21 34 0a aa")
IMPEDANCE = bytes.fromhex("5a 0b 26 11 00 00 00 00 00 01 89 b4 aa")


class FakeClient:
    """Replies to the hello and the stable-weight ack like the scale."""

    def __init__(
        self, *, send_stable: bool = True, send_impedance: bool = True
    ) -> None:
        self.written: list[bytes] = []
        self.send_stable = send_stable
        self.send_impedance = send_impedance
        self._callback: Callable[[Any, bytearray], None] | None = None
        self.disconnect = AsyncMock()

    async def start_notify(
        self, _: str, callback: Callable[[Any, bytearray], None]
    ) -> None:
        self._callback = callback

    async def write_gatt_char(self, _: str, data: bytes, *, response: bool) -> None:
        assert response
        assert self._callback is not None
        self.written.append(data)
        if data == HELLO_COMMANDS[-1]:
            self._callback(None, bytearray(SETTLING))
            if self.send_stable:
                self._callback(None, bytearray(STABLE))
        elif data == ACK_STABLE_WEIGHT and self.send_impedance:
            self._callback(None, bytearray(IMPEDANCE))


async def test_full_measurement() -> None:
    client = FakeClient()
    assert await async_measure(client) == Measurement(  # type: ignore[arg-type]
        weight_kg=85.0, impedance_ohm=393
    )
    assert client.written == [*HELLO_COMMANDS, ACK_STABLE_WEIGHT, ACK_IMPEDANCE]


async def test_weight_only() -> None:
    client = FakeClient(send_impedance=False)
    result = await async_measure(client, impedance_timeout=0.01)  # type: ignore[arg-type]
    assert result == Measurement(weight_kg=85.0, impedance_ohm=None)


async def test_no_stable_weight() -> None:
    client = FakeClient(send_stable=False)
    assert await async_measure(client, weight_timeout=0.01) is None  # type: ignore[arg-type]
    assert ACK_STABLE_WEIGHT not in client.written


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


def test_poll_needed() -> None:
    data = VitafitBluetoothDeviceData()
    info = service_info("Vitafit Body Fat")
    assert data.poll_needed(info, None)
    assert not data.poll_needed(info, 10)
    assert data.poll_needed(info, 61)


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
    assert update.entity_values[DeviceKey("mass")].native_value == 85.0
    assert update.entity_values[DeviceKey("impedance")].native_value == 393
