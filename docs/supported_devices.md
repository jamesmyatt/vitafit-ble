# Supported devices

`VitafitBluetoothDeviceData` detects the scale from its advertisement; there is
no model selection.

| Model   | Family         | Transport | Detection                                              | Sensors                                  |
| ------- | -------------- | --------- | ------------------------------------------------------ | ---------------------------------------- |
| `VT701` | Body fat scale | GATT poll | local name starting `Vitafit`, e.g. `Vitafit Body Fat` | weight (kg), impedance (Ω), display unit |

This library has been tested with a real VT701, and its test suite uses frames
captured from it. See [Protocol](protocol.md) for where the protocol comes from.

## Transport guide

- **GATT poll**: the scale's advertisement carries no readings, so
  `async_poll()` connects and runs a weigh-in. See [Usage](usage.md) for the
  sequence and [Protocol](protocol.md) for the frames.

## Not supported

These are out of scope for this library:

- **Body composition** (body fat, muscle, water, bone mass, BMI and so on).
  The Vitafit app calculates these from weight, impedance and a user profile
  (height, age and sex). The scale itself only reports weight and impedance.
- **User profiles** and assigning readings to people.

If you have a Vitafit scale that looks like it should work but is not
detected, open an issue with a capture from `scripts/capture.py` (see
[Capturing frames](protocol.md#capturing-frames)), or a BLE advertisement
capture from `bluetoothctl`.
