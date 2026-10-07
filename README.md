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

`async_measure` returns:

- `None` if no stable weight is received within 30 s.
- A `Measurement` with `weight_kg` (0.01 kg resolution), `impedance_ohm` and `display_unit`. `impedance_ohm` is `None` if the scale can't measure impedance, for example through socks, or doesn't report it within 10 s, for example when you step off early. `display_unit` is the unit the scale was showing (`DisplayUnit.KG`, `LB` or `ST`); the weight is in kg either way.

`VitafitBluetoothDeviceData` wraps the same session for Home Assistant's `ActiveBluetoothProcessorCoordinator`.

See [usage](docs/usage.md) for details.

## Licence

MIT
