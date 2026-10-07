(usage)=

# Usage

See [Supported devices](supported_devices.md) for the recognised model and the
transport it uses.

`vitafit-ble` connects to a Vitafit scale over GATT, runs one weigh-in, and
turns the result into structured sensor values. It is built on top of
[`bluetooth-sensor-state-data`](https://github.com/Bluetooth-Devices/bluetooth-sensor-state-data)
and is the library used by the
[Vitafit Home Assistant integration](https://github.com/jamesmyatt/ha-vitafit-ble),
but it can be used on its own.

The entry point is the `VitafitBluetoothDeviceData` class:

```python
from vitafit_ble import VitafitBluetoothDeviceData
```

## Detecting the scale (advertisement)

The scale only advertises while it is awake, after someone steps on it. Its
advertisement identifies the scale but carries no readings. Feed each
advertisement to `update()` and you get a `SensorUpdate` back with the device
details and signal strength:

```python
from vitafit_ble import VitafitBluetoothDeviceData

# `service_info` is a habluetooth `BluetoothServiceInfoBleak`. Inside Home
# Assistant you receive one for every advertisement; standalone you can build
# one from a Bleak scan (see below).
data = VitafitBluetoothDeviceData()

if data.supported(service_info):
    update = data.update(service_info)
    print(data.title)  # e.g. Vitafit VT701 EEFF
    print(update.entity_values)
```

## Reading a weigh-in (connect and subscribe)

The readings come over a GATT connection. `vitafit-ble` handles the connection
for you via [Bleak](https://github.com/hbldh/bleak) and
[`bleak-retry-connector`](https://github.com/Bluetooth-Devices/bleak-retry-connector);
you only supply a `BLEDevice`.

Check `poll_needed()` and call `async_poll()` with a `BLEDevice`:

```python
if data.poll_needed(service_info, last_poll=None):
    update = await data.async_poll(ble_device)
    print(update.entity_values)
```

`poll_needed()` rate-limits itself, so it is safe to call on every
advertisement: it returns `True` for the first advertisement and then at most
once every 60 s, so one weigh-in is read once.

`async_poll()` connects, subscribes to notifications, sends the start
commands and waits up to 30 s for a stable weight. It then acknowledges the weight,
waits up to 10 s for the impedance, and disconnects. The scale keeps its
display unit (kg, lb or st); the weight is always in kg. See
[Protocol](protocol.md) for the frames.

Keyword arguments to `async_poll()` are passed to `async_measure()` (see
below), for example `await data.async_poll(ble_device, weight_only=True)`.

`async_poll()` returns a `SensorUpdate` whose `entity_values` maps each
`DeviceKey` to a `SensorValue` (weight in kg, impedance in Ω, signal strength
in dBm):

```python
for device_key, sensor_value in update.entity_values.items():
    print(device_key.key, sensor_value.native_value)
# signal_strength -60
# mass 87.35
# impedance 466
```

`impedance` is `None` if the scale can't measure it, for example through
socks, or doesn't report it within 10 s, for example when you step off early. If no stable weight arrives, or
the Bluetooth connection fails, the update has no `mass` or `impedance`; the
failure is logged.

### Using the measurement session directly

If you already have a connected `BleakClient`, run the session yourself with
`async_measure()`:

```python
from bleak import BleakClient
from vitafit_ble import async_measure

async with BleakClient(address) as client:
    measurement = await async_measure(client)
```

`async_measure()` returns `None` if no stable weight arrives within 30 s.
Otherwise it returns a `Measurement` with `weight_kg`, `impedance_ohm` and
`display_unit`, the unit the scale was showing (`DisplayUnit.KG`, `LB` or
`ST`). The weight is in kg whatever the display unit.

To also set the scale's display unit, pass `display_unit`:

```python
from vitafit_ble import DisplayUnit, async_measure

measurement = await async_measure(client, display_unit=DisplayUnit.ST)
```

The display changes straight away. `measurement.display_unit` always comes
from the scale's stable weight frame. Without `display_unit`, the scale keeps
its current unit.

To weigh without passing any current through the body, as the Vitafit app's
"Weight Only Mode" does, pass `weight_only=True`:

```python
measurement = await async_measure(client, weight_only=True)
```

`measurement.impedance_ohm` is then always `None`. Each weigh-in sets the
mode, so without `weight_only` the scale measures impedance. The scale keeps
the mode for later weigh-ins without a connection.

## Building a `BluetoothServiceInfoBleak` outside Home Assistant

When you are not running inside Home Assistant you can construct the
`service_info` yourself from a Bleak scan result:

```python
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
    time=0,
    tx_power=advertisement_data.tx_power or 0,
    raw=None,
)
```

`device` and `advertisement_data` are the `BLEDevice` and `AdvertisementData`
objects yielded by `bleak.BleakScanner`.
