# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `async_measure()` runs one weigh-in on a connected `BleakClient` and returns
  a `Measurement` with weight (kg), whole-body impedance (Ω) and the scale's
  display unit.
- `VitafitBluetoothDeviceData` detects the Vitafit VT701 from its advertisement
  and reads a weigh-in with `poll_needed()` and `async_poll()`, for Home
  Assistant's `ActiveBluetoothProcessorCoordinator`.
- Frame codec for the VT701 GATT protocol, from openScale's VT701 handler.
- The scale keeps its display unit (kg, lb or st) after a weigh-in;
  `async_measure(display_unit=...)` sets it instead. Readings are always in kg.
- `async_measure(weight_only=True)` selects the scale's weight-only mode, which
  passes no current, so no impedance is measured.

[Unreleased]: https://github.com/jamesmyatt/vitafit-ble/commits/main
