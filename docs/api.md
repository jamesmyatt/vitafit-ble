# API reference

Auto-generated reference for `vitafit_ble`. For task-oriented examples, see
[usage](usage.md).

## Device

`supported()` and `device_name()` work on advertisements. `poll_needed()` says
when to connect, and `async_poll()` connects and runs a weigh-in.

```{eval-rst}
.. autofunction:: vitafit_ble.supported

.. autofunction:: vitafit_ble.device_name

.. autofunction:: vitafit_ble.poll_needed

.. autofunction:: vitafit_ble.async_poll
```

## Measurement session

`async_measure()` runs one weigh-in with the default options on a connected
`BleakClient`. For options or frame callbacks, use a `VitafitSession`.

```{eval-rst}
.. autofunction:: vitafit_ble.async_measure

.. autoclass:: vitafit_ble.VitafitSession

    .. automethod:: register_callback
    .. automethod:: async_measure
    .. automethod:: on_send
    .. automethod:: on_receive

.. autoclass:: vitafit_ble.Frame

.. autoclass:: vitafit_ble.WeightFrame
    :members:

.. autoclass:: vitafit_ble.WeightFlag
    :members:

.. autoclass:: vitafit_ble.ImpedanceFrame
    :members:

.. autoclass:: vitafit_ble.ImpedanceCode
    :members:

.. autoclass:: vitafit_ble.Measurement
    :members:
```

## Frame codec

`vitafit_ble.protocol` decodes the scale's frames. It is a developer reference
for debugging and tests, such as `scripts/capture.py`; see
[Protocol](protocol.md) for the frames themselves.

```{eval-rst}
.. autofunction:: vitafit_ble.protocol.decode

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
