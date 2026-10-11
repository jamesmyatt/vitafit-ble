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

It returns a `Measurement` with `weight_kg` (always kg), `impedance_ohm` and `display_unit`, or `None` if no stable weight arrives within 30 s. `impedance_ohm` is `None` if impedance isn't measured, for example through socks or if you step off early.

For options or callbacks, such as the live weight, use a `VitafitSession`. For example, the Vitafit app's "Weight Only Mode" skips impedance, and the scale keeps it for later offline weigh-ins:

```python
from vitafit_ble import VitafitSession

measurement = await VitafitSession(weight_only=True).async_measure(client)
```

For Home Assistant, `poll_needed()` says when to connect, and `async_poll()` connects, runs a weigh-in and disconnects. See [usage](docs/usage.md) for details.

## Licence

MIT. The protocol is based on openScale's
[VT701 handler](https://github.com/oliexdev/openScale/pull/1423).
