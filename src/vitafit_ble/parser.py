"""Home Assistant-style device data for the Vitafit VT701."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from bluetooth_data_tools import short_address
from bluetooth_sensor_state_data import BluetoothData
from sensor_state_data import SensorLibrary, SensorUpdate

from .const import LOCAL_NAME_PREFIX, MANUFACTURER, MODEL, POLL_INTERVAL
from .session import async_measure

if TYPE_CHECKING:
    from bleak.backends.device import BLEDevice
    from habluetooth import BluetoothServiceInfo

_LOGGER = logging.getLogger(__name__)


class VitafitBluetoothDeviceData(BluetoothData):
    """Data for a Vitafit VT701 scale."""

    def _start_update(self, service_info: BluetoothServiceInfo) -> None:
        """Update from a BLE advertisement."""
        if not (service_info.name or "").startswith(LOCAL_NAME_PREFIX):
            return
        self.set_device_manufacturer(MANUFACTURER)
        self.set_device_type(MODEL)
        name = f"{MANUFACTURER} {MODEL} {short_address(service_info.address)}"
        self.set_device_name(name)
        self.set_title(name)

    def poll_needed(
        self,
        service_info: BluetoothServiceInfo,  # noqa: ARG002
        last_poll: float | None,
    ) -> bool:
        """Return True if the scale should be connected to.

        True for the first advertisement, then at most once every
        ``POLL_INTERVAL`` (60 s), so one weigh-in is read once. Safe to call on
        every advertisement. The scale only advertises while awake, i.e. after
        being stepped on.
        """
        return last_poll is None or last_poll > POLL_INTERVAL

    async def async_poll(
        self,
        ble_device: BLEDevice,
        **measure_kwargs: Any,  # noqa: ANN401
    ) -> SensorUpdate:
        """Connect, read one weigh-in and disconnect.

        The update has ``mass`` and ``impedance`` (``None`` if the scale
        couldn't measure it). If no stable weight arrives, or a Bluetooth error
        occurs, the update has no readings; the error is logged as a warning.

        ``measure_kwargs`` are passed to ``async_measure``, for example
        ``weight_only=True``.
        """
        _LOGGER.debug("Polling Vitafit scale: %s", ble_device.address)
        client = await establish_connection(
            BleakClientWithServiceCache, ble_device, ble_device.address
        )
        try:
            measurement = await async_measure(client, **measure_kwargs)
        except BleakError as err:
            _LOGGER.warning("%s: weigh-in failed: %s", ble_device.address, err)
            return self._finish_update()
        finally:
            await client.disconnect()
            _LOGGER.debug("%s: disconnected", ble_device.address)

        if measurement is None:
            _LOGGER.debug("%s: no stable weight received", ble_device.address)
        else:
            self.update_predefined_sensor(
                SensorLibrary.MASS__MASS_KILOGRAMS, measurement.weight_kg
            )
            self.update_predefined_sensor(
                SensorLibrary.IMPEDANCE__OHM, measurement.impedance_ohm
            )
        return self._finish_update()
