# vitafit-ble

Bluetooth client for the Vitafit VT701 body fat scale. It reads weight and whole-body impedance.

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
- A `Measurement` with `weight_kg` (0.01 kg resolution) and `impedance_ohm`. `impedance_ohm` is `None` if the scale does not report impedance within 6 s, for example when you step off early or are wearing socks.

`VitafitBluetoothDeviceData` wraps the same session for Home Assistant's `ActiveBluetoothProcessorCoordinator`.

## Protocol

GATT service `0xFFF0`. The scale notifies on `0xFFF1`; the client writes on `0xFFF2`.

| Direction | Frame | Meaning |
|---|---|---|
| Client → scale | `a5 05 26 33 00 10 aa`, `a5 04 26 44 66 aa`, `a5 05 26 17 01 35 aa` | Hello sequence |
| Scale → client | `5a 0a 26 10 <flag> 00 00 21 <w_hi> <w_lo> <chk> aa` | Weight, 0.01 kg, big-endian. `flag` 0x02 = stable. |
| Client → scale | `a5 05 26 10 02 31 aa` | Acknowledge stable weight; starts the impedance measurement |
| Scale → client | `5a 0b 26 11 00 00 00 00 00 <z_hi> <z_lo> <chk> aa` | Impedance, Ω, big-endian |
| Client → scale | `a5 05 26 11 00 32 aa` | Acknowledge impedance |

Frame layout is `[header][length][0x26][type][data…][checksum][0xAA]`:

- `length` counts the bytes after itself.
- `checksum` is the XOR of `length` through the last data byte.

The protocol and test vectors come from openScale's [VT701 handler](https://github.com/oliexdev/openScale/pull/1423).

## Licence

MIT
