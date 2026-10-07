# vitafit-ble

Bluetooth library for Vitafit devices. See [supported devices](docs/supported_devices.md) for the models it works with.

Unofficial; not affiliated with Vitafit.

## Install

```sh
pip install vitafit-ble
```

## Use

```python
from bleak import BleakClient
from vitafit_ble import async_measure

async with BleakClient(address) as client:
    measurement = await async_measure(client)
```

It returns a `Measurement` with `weight_kg`, `impedance_ohm` and `display_unit`, or `None` if no stable weight arrives within 30 s. Weight is always in kg. `impedance_ohm` is `None` if impedance isn't measured, for example through socks or if you step off early.

Pass `weight_only=True` to skip impedance (the Vitafit app's "Weight Only Mode"). The scale keeps this mode for later offline weigh-ins.

`VitafitBluetoothDeviceData` wraps the same session for Home Assistant; its `async_poll` passes `weight_only` through.

See [usage](docs/usage.md) for details.

## Licence

MIT. The protocol is based on openScale's
[VT701 handler](https://github.com/oliexdev/openScale/pull/1423).
