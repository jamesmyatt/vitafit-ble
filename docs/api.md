# API reference

Auto-generated reference for `vitafit_ble`. For task-oriented examples, see
[usage](usage.md).

The package also re-exports the
[`sensor-state-data`](https://github.com/Bluetooth-Devices/sensor-state-data)
types that its updates use: `SensorUpdate`, `DeviceKey`, `SensorValue`,
`SensorDescription`, `SensorDeviceInfo`, `DeviceClass` and `Units`. See
`sensor-state-data` for those.

## Device data

`VitafitBluetoothDeviceData` is the entry point. `supported()`, `update()` and
`title` come from
[`bluetooth-sensor-state-data`](https://github.com/Bluetooth-Devices/bluetooth-sensor-state-data)'s
`BluetoothData`.

```{eval-rst}
.. autoclass:: vitafit_ble.VitafitBluetoothDeviceData

    .. automethod:: supported
    .. automethod:: update
    .. autoproperty:: title
    .. automethod:: poll_needed
    .. automethod:: async_poll
```

## Measurement session

`async_measure()` runs one weigh-in on a `BleakClient` you have already
connected. `async_poll()` uses it.

```{eval-rst}
.. autofunction:: vitafit_ble.async_measure

.. autoclass:: vitafit_ble.Measurement
    :members:
```

## Frame codec

`vitafit_ble.protocol` decodes the scale's frames. It is a developer reference
for debugging and tests, such as `scripts/capture.py`; see
[Protocol](protocol.md) for the frames themselves.

```{eval-rst}
.. autofunction:: vitafit_ble.protocol.decode

.. autoclass:: vitafit_ble.protocol.WeightFrame
    :members:

.. autoclass:: vitafit_ble.protocol.ImpedanceFrame
    :members:

.. autoclass:: vitafit_ble.protocol.DisplayUnit
    :members:
    :undoc-members:

.. autofunction:: vitafit_ble.protocol.unit_command
```

## Constants

```{eval-rst}
.. autodata:: vitafit_ble.const.LOCAL_NAME_PREFIX

.. autodata:: vitafit_ble.const.WEIGHT_TIMEOUT

.. autodata:: vitafit_ble.const.IMPEDANCE_TIMEOUT

.. autodata:: vitafit_ble.const.POLL_INTERVAL

.. autodata:: vitafit_ble.const.ADVERTISEMENT_MAX_AGE
```
