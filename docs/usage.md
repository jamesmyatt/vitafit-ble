(usage)=

# Usage

`vitafit-ble` reads one weigh-in from a Vitafit scale over GATT, with the live
weight as you stand on it. The
[Vitafit Home Assistant integration](https://github.com/jamesmyatt/ha-vitafit-ble)
uses it. See [Supported devices](supported_devices.md) for the models.

## Detecting the scale

The scale only advertises while it's awake, after someone steps on it. The
advertisement identifies it but carries no readings:

```python
from vitafit_ble import device_name, supported

# service_info is a habluetooth BluetoothServiceInfoBleak (see below).
if supported(service_info):
    print(device_name(service_info.address))  # e.g. Vitafit VT701 EEFF
```

## Reading a weigh-in

`async_poll()` connects with
[`bleak-retry-connector`](https://github.com/Bluetooth-Devices/bleak-retry-connector),
runs a weigh-in and disconnects. Call it when `poll_needed()` is true:

```python
from vitafit_ble import async_poll, poll_needed

if poll_needed(service_info, last_poll=None):
    measurement = await async_poll(ble_device)
# Measurement(weight_kg=87.35, impedance_ohm=466, display_unit=<DisplayUnit.KG: 1>)
```

`poll_needed()` is true for the first advertisement, then at most once every
60 s, so a weigh-in is read once. The advertisement must also be at most 5 s
old, so it's safe to call from a timer: it's false once the scale sleeps.

The weigh-in waits up to 30 s for a stable weight, acknowledges it, then waits
up to 10 s for impedance. The weight is always in kg, whatever the scale
displays. `impedance_ohm` is `None` if the scale can't measure it, for example
through socks, or you step off early. If no stable weight arrives,
`async_poll()` returns `None`. A Bluetooth error, connecting or during the
weigh-in, raises `BleakError` after disconnecting. `async_poll()` doesn't log
it, so you can log a run of failures once.

If you already have a connected `BleakClient`, use `async_measure(client)`
instead. See [Protocol](protocol.md) for the frames.

## Options

Create a `VitafitSession` with the options, and call its `async_measure()` with
the client, or pass it to `async_poll()`:

```python
from vitafit_ble import DisplayUnit, VitafitSession

measurement = await VitafitSession(weight_only=True).async_measure(client)
measurement = await async_poll(ble_device, VitafitSession(display_unit=DisplayUnit.ST))
```

- `weight_only=True` selects the Vitafit app's "Weight Only Mode", which passes
  no current, so `impedance_ohm` is `None`. The scale keeps the mode for later
  weigh-ins without a connection.
- `display_unit` sets the scale's display unit (kg, lb or st). Without it, the
  scale keeps its unit. `measurement.display_unit` is the unit it was showing.
- `ack_every_frame=False` acknowledges only the stable weight and the
  impedance, as openScale does. By default each settling and stable weight
  frame is also acknowledged, as the Vitafit app does, so that the scale can
  replace any frame that went missing or failed its checks.
- `weight_timeout` and `impedance_timeout` change the waits.

## Seeing each frame

Register a callback for `WeightFrame` (about every 0.36 s), `ImpedanceFrame`,
or `Frame` for both. It returns a function that unregisters it:

```python
from vitafit_ble import Frame, VitafitSession, WeightFrame


def on_weight(frame):
    print(frame.weight_kg, "stable" if frame.stable else "settling")


session = VitafitSession()
unregister = session.register_callback(WeightFrame, on_weight)
session.register_callback(Frame, print)
measurement = await session.async_measure(client)
```

A frame's callbacks run in the order registered, whatever their type. For the raw
bytes of every command and notification, override `on_send` and `on_receive`:

```python
class PrintingSession(VitafitSession):
    def on_send(self, data):
        print("TX", data.hex(" "))

    def on_receive(self, data):
        print("RX", data.hex(" "))
```

These only observe the exchange. `on_receive` runs as each notification
arrives, including after `async_measure()` returns, until you disconnect. The
callbacks run during `async_measure()` as it takes each frame, before the
frame's acknowledgement is sent, so they stop when it returns. An exception from a callback ends the weigh-in, and
`async_measure()` raises it. `scripts/capture.py` logs a weigh-in this way.

## Building a `BluetoothServiceInfoBleak` outside Home Assistant

From a `bleak.BleakScanner` result (`device` and `advertisement_data`):

```python
from bluetooth_data_tools import monotonic_time_coarse
from habluetooth import BluetoothServiceInfoBleak

service_info = BluetoothServiceInfoBleak(
    name=device.name,
    address=device.address,
    rssi=advertisement_data.rssi,
    manufacturer_data=advertisement_data.manufacturer_data,
    service_data=advertisement_data.service_data,
    service_uuids=advertisement_data.service_uuids,
    source="local",
    device=device,
    advertisement=advertisement_data,
    connectable=True,
    time=monotonic_time_coarse(),  # poll_needed() checks it's recent
    tx_power=advertisement_data.tx_power or 0,
    raw=None,
)
```
