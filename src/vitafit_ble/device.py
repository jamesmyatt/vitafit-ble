"""Find a Vitafit VT701 and read a weigh-in, for Home Assistant and similar."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from bluetooth_data_tools import monotonic_time_coarse, short_address

from .const import (
    ADVERTISEMENT_MAX_AGE,
    LOCAL_NAME_PREFIX,
    MANUFACTURER,
    MODEL,
)
from .session import async_measure

if TYPE_CHECKING:
    from bleak.backends.device import BLEDevice
    from habluetooth import BluetoothServiceInfo, BluetoothServiceInfoBleak

    from .session import Measurement, VitafitSession

_LOGGER = logging.getLogger(__name__)


def supported(service_info: BluetoothServiceInfo) -> bool:
    """Return True if the advertisement is from a Vitafit scale."""
    return (service_info.name or "").startswith(LOCAL_NAME_PREFIX)


def device_name(address: str) -> str:
    """Return a name for the scale at ``address``, e.g. ``Vitafit VT701 EEFF``."""
    return f"{MANUFACTURER} {MODEL} {short_address(address)}"


def awake(service_info: BluetoothServiceInfoBleak) -> bool:
    """Return True if the scale is awake, so it can be connected to.

    The scale only advertises while awake, after being stepped on, so the
    advertisement must be at most ``ADVERTISEMENT_MAX_AGE`` (5 s) old. This lets
    a timer call it with the latest advertisement, which Home Assistant doesn't
    dispatch when it repeats the previous one. When to poll again is up to the
    caller: after a weigh-in, a new connection gets no weight frames until the
    scale has slept and woken again.
    """
    return monotonic_time_coarse() - service_info.time <= ADVERTISEMENT_MAX_AGE


async def async_poll(
    ble_device: BLEDevice, session: VitafitSession | None = None
) -> Measurement | None:
    """Connect, read one weigh-in and disconnect.

    ``session`` sets the options and callbacks, as for ``async_measure``, for
    example ``await async_poll(ble_device, VitafitSession(weight_only=True))``.

    Return None if no stable weight arrives, or if the impedance arrives
    first. A Bluetooth error, connecting or during the weigh-in, raises
    ``BleakError``, after disconnecting. It isn't logged, so the caller can log
    a run of failures once.
    """
    _LOGGER.debug("Polling Vitafit scale: %s", ble_device.address)
    client = await establish_connection(
        BleakClientWithServiceCache, ble_device, ble_device.address
    )
    try:
        return await async_measure(client, session)
    finally:
        await client.disconnect()
        _LOGGER.debug("%s: disconnected", ble_device.address)
