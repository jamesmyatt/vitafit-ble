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
    POLL_INTERVAL,
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


def poll_needed(
    service_info: BluetoothServiceInfoBleak, last_poll: float | None
) -> bool:
    """Return True if the scale should be connected to.

    ``last_poll`` is the seconds since the last poll, or None if there hasn't
    been one. True for the first advertisement, then at most once every
    ``POLL_INTERVAL`` (60 s), so one weigh-in is read once. Safe to call on
    every advertisement. The scale only advertises while awake, i.e. after
    being stepped on, so the advertisement must also be at most
    ``ADVERTISEMENT_MAX_AGE`` (5 s) old. This lets a timer call it with the
    latest advertisement, which Home Assistant doesn't dispatch when it repeats
    the previous one.
    """
    return (last_poll is None or last_poll > POLL_INTERVAL) and (
        monotonic_time_coarse() - service_info.time <= ADVERTISEMENT_MAX_AGE
    )


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
