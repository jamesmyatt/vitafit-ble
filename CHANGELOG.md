# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.5.0] - 2026-10-17

### Added

- `VitafitSession(ack_every_frame=False)` acknowledges only the stable weight
  and the impedance, as openScale does.
- `ImpedanceFrame.code`: the raw value when there's no impedance reading, an
  `ImpedanceCode` (`FAILED` or `WEIGHT_ONLY`) if it's a known one.
  `ImpedanceCode` is exported from `vitafit_ble`.
- Python 3.15 support, tested in CI.
- A Python version policy in the installation docs: supported and tested from
  the version the latest stable Home Assistant Core release requires (3.14),
  with older versions back to 3.11 on a best-effort basis.

### Changed

- **The weigh-in acknowledges every weight and impedance frame that decodes,
  as the Vitafit app does, so that the scale replaces any frame that went
  missing or failed its checks. It used to acknowledge only the stable weight
  and the impedance.**
- **Frame callbacks run during `async_measure()`, after any acknowledgement of
  the frame, instead of as each notification arrives, so they stop when it
  returns. `on_receive()` still sees every notification until disconnecting.
  An exception from a callback now ends the weigh-in, and `async_measure()`
  raises it.**
- **An impedance frame ends the weigh-in even before a stable weight, so
  `async_measure()` returns `None` straight away instead of waiting for the
  weight timeout.**
- **A frame's callbacks run in the order registered. `Frame` callbacks used to
  run after those for the frame's own class.**

## [0.4.0] - 2026-10-12

### Changed

- `async_poll()` raises `BleakError` if a Bluetooth error occurs during the
  weigh-in, as it already did if it couldn't connect. It used to return `None`
  and log a warning. It now returns `None` only if no stable weight arrives,
  and logs at debug level only, so the caller can log a run of failures once.

## [0.3.0] - 2026-10-11

### Added

- `VitafitSession`: the weigh-in options and callbacks.
  `register_callback(frame_type, callback)` gets each decoded `WeightFrame` or
  `ImpedanceFrame`, or both with `Frame`, for example for the live weight.
  Override `on_send()` and `on_receive()` for the raw bytes.
- `Frame`, the base class of `WeightFrame` and `ImpedanceFrame`. All three are
  exported from `vitafit_ble`.
- `supported()` and `device_name()` for advertisements.

### Changed

- `async_measure()` takes an optional `VitafitSession` instead of keyword
  arguments. The options are unchanged; use
  `VitafitSession(weight_only=True).async_measure(client)`.
- `poll_needed()` and `async_poll()` are now functions; they were
  `VitafitBluetoothDeviceData` methods. `async_poll()` takes an optional
  `VitafitSession` instead of keyword arguments, and returns a `Measurement`
  instead of a `SensorUpdate`, or `None` if no stable weight arrives or the
  connection drops during the weigh-in.
- `scripts/capture.py` logs through `VitafitSession`. Decoded frames are now
  separate `frame` events, not a `decoded` field on `rx` events.

### Removed

- `VitafitBluetoothDeviceData`; use the `supported()`, `device_name()`,
  `poll_needed()` and `async_poll()` functions.
- The `bluetooth-sensor-state-data` and `sensor-state-data` dependencies, and
  the re-exported `SensorUpdate`, `DeviceKey`, `SensorValue`,
  `SensorDescription`, `SensorDeviceInfo`, `DeviceClass` and `Units`.

## [0.2.0] - 2026-10-08

### Changed

- `poll_needed()` is also `False` unless the advertisement is at most
  `ADVERTISEMENT_MAX_AGE` (5 s) old, so a timer can call it with the latest
  advertisement without connecting to a sleeping scale. It now takes a
  `BluetoothServiceInfoBleak`, which has the advertisement's `time`.

## [0.1.0] - 2026-10-07

First release. Supports the Vitafit VT701 body fat scale, which advertises as
"Vitafit Body Fat", and has been tested on a real scale. The protocol is based on
openScale's VT701 handler.

### Added

- `async_measure()` runs one weigh-in on a connected `BleakClient` and returns
  a `Measurement`, or `None` if no stable weight arrives within
  `weight_timeout` (default 30 s). A `Measurement` has:
  - `weight_kg`: the stable weight, to 0.01 kg, whatever unit the scale
    displays.
  - `impedance_ohm`: whole-body impedance in Ω, or `None` if the scale couldn't
    measure it (for example through socks) or didn't send it within
    `impedance_timeout` (default 10 s), for example because the user stepped
    off early.
  - `display_unit`: the unit the scale was showing, as a `DisplayUnit`.
- `async_measure(weight_only=True)` selects the scale's weight-only mode, which
  passes no current, so `impedance_ohm` is `None`. Every call sets the mode, and
  the scale keeps it for weigh-ins made without a connection.
- `async_measure(display_unit=...)` sets the scale's display unit to kg, lb or
  st. By default the display unit is left unchanged.
- `VitafitBluetoothDeviceData`, for Home Assistant's
  `ActiveBluetoothProcessorCoordinator`. It recognises the scale by its
  advertised name, and `async_poll()` connects, reads one weigh-in as `mass`
  and `impedance` sensors, then disconnects. `poll_needed()` asks for a poll
  at most once every 60 s. Keyword arguments to `async_poll()`, such as
  `weight_only`, are passed to `async_measure()`.
- Type hints (`py.typed`). Requires Python 3.11 or later.

[Unreleased]: https://github.com/jamesmyatt/vitafit-ble/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/jamesmyatt/vitafit-ble/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/jamesmyatt/vitafit-ble/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/jamesmyatt/vitafit-ble/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/jamesmyatt/vitafit-ble/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/jamesmyatt/vitafit-ble/releases/tag/v0.1.0
