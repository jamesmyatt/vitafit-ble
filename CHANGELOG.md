# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/jamesmyatt/vitafit-ble/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/jamesmyatt/vitafit-ble/releases/tag/v0.1.0
