# Supported devices

`vitafit-ble` recognises the following Vitafit model. There is no model
selection: `VitafitBluetoothDeviceData` detects the scale from its
advertisement, and `VitafitBluetoothDeviceData.supported(service_info)` returns
true for it.

| Model   | Family         | Transport | Detection                                              | Sensors                                  |
| ------- | -------------- | --------- | ------------------------------------------------------ | ---------------------------------------- |
| `VT701` | Body fat scale | GATT poll | local name starting `Vitafit`, e.g. `Vitafit Body Fat` | weight (kg), impedance (Ω), display unit |

The protocol combines openScale's
[VT701 handler](https://github.com/oliexdev/openScale/pull/1423) with captures
from a real VT701 (see [Protocol](protocol.md)). This library has
been tested with that scale, and its test suite uses frames captured from it.

## Transport guide

- **GATT poll**: the scale only advertises while it is awake, after someone
  steps on it, and its advertisement carries no readings. When `poll_needed()`
  returns true (at most once every 60 s), call `async_poll(ble_device)`. Within
  the poll, it connects, subscribes to notifications on `0xFFF1`, sends the
  mode and hello commands on `0xFFF2`, and the readings arrive as notifications. It
  waits up to 30 s for a stable weight, acknowledges it (openScale says this
  starts the impedance measurement), and waits up to 10 s for the impedance. It
  then disconnects. See [Protocol](protocol.md) for the frames.
- **Impedance** is only measured barefoot. In socks, the scale reports that
  it couldn't measure impedance; if you step off early, it reports nothing.
  Either way, `async_poll` still returns the weight, with no impedance.

## Not supported

These are out of scope for this library:

- **Body composition** (body fat, muscle, water, bone mass, BMI and so on).
  The Vitafit app calculates these from weight, impedance and a user profile
  (height, age and sex). The scale itself only reports weight and impedance.
- **User profiles** and assigning readings to people.

Weight is always reported in kg. The scale keeps whichever display unit it is
set to (kg, lb or st), unless you set one with
`async_measure(client, display_unit=...)`. To skip impedance, as the Vitafit
app's "Weight Only Mode" does, use `async_measure(client, weight_only=True)`.

If you have a Vitafit scale that looks like it should work but is not
detected, open an issue with a capture from `scripts/capture.py` (see
[Capturing frames](protocol.md#capturing-frames)), or a BLE advertisement
capture from `bluetoothctl`.
