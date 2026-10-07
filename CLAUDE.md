# CLAUDE.md: vitafit-ble

Python library (PyPI `vitafit-ble`, MIT) for the Vitafit VT701 body fat scale. It reads weight and impedance over BLE GATT.

It is used by the Home Assistant integration in the sibling repo `../ha-vitafit-ble`. Read that repo's `CLAUDE.md` for the owner's preferences, the decisions already made, the research and the overall next steps.

## Status (5 Oct 2026)

- Complete, with one initial commit. Not yet on PyPI (404). Not yet tested on a real scale.

## Scope

- Weight (kg) and whole-body impedance (Ω) only. The owner decided against body composition, user profiles and unit setting; HA does those.
- The library is modelled on core's `oralb-ble`:
  - `VitafitBluetoothDeviceData` subclasses `bluetooth_sensor_state_data.BluetoothData`.
  - It provides `poll_needed()` and `async_poll()` for HA's `ActiveBluetoothProcessorCoordinator`.
- It has no `homeassistant` imports. It does use `home-assistant-bluetooth` and `sensor-state-data`, as `oralb-ble` does.

## Modules

- `protocol.py`: pure frame codec with no I/O.
  - `decode()` validates the header, length, product byte, trailer and XOR checksum.
  - It returns `WeightFrame`, `ImpedanceFrame` or `None`.
  - Impedance outside 1–1499 Ω becomes `None`, matching openScale's guard.
- `session.py`: `async_measure(client)` on an already-open `BleakClient`:
  1. Subscribe to notifications on 0xFFF1.
  2. Write the three hello commands to 0xFFF2 with response.
  3. Wait up to 30 s for a stable weight frame (byte 4 = 0x02). If none arrives, return `None`.
  4. Write the stable-weight ack. This makes the scale measure impedance.
  5. Wait up to 6 s for an impedance frame. If none arrives, return weight only.
  6. Write the impedance ack.
- `parser.py`: `VitafitBluetoothDeviceData`.
  - It recognises the scale by a local name starting with "Vitafit".
  - The device and title name is `Vitafit VT701 <last 4 hex digits of the MAC>`.
  - `poll_needed` returns true if there has been no poll yet, or the last poll was more than 60 s ago.
  - `async_poll` calls `establish_connection(BleakClientWithServiceCache, …)`, then `async_measure`, then always disconnects.

## Protocol

Source: openScale [PR #1423](https://github.com/oliexdev/openScale/pull/1423), `VitafitVT701Handler.kt`.

- Treat this as correct, because the owner's scale works with openScale.
- The test vectors in `tests/test_protocol.py` come from openScale's `VitafitVT701HandlerTest.kt`. They are real HCI captures: 85.00 kg with 393 Ω, and 84.95 kg with 389 Ω.

The frame format and command table are in `README.md`. Key facts:

- Frame layout: `[5A|A5][len][26][type][data…][xor(len..data)][AA]`.
- Weight: type 0x10, bytes 8–9, big-endian, in units of 0.01 kg.
- Impedance: type 0x11, bytes 9–10, big-endian, in Ω.

## Commands

```sh
uv sync                      # Python 3.13+ (CI tests 3.13 and 3.14)
uv run ruff format --check .
uv run ruff check .          # select = ALL, with a few ignores
uv run mypy src tests        # strict
uv run pytest                # 17 tests
uv build
```

## Release

Releases are published by `.github/workflows/release.yml` when a GitHub release is published. It uses PyPI trusted publishing, so no token is needed.

One-off setup: on PyPI, add a pending trusted publisher with these settings:

- Project `vitafit-ble`
- Owner `jamesmyatt`
- Repo `vitafit-ble`
- Workflow `release.yml`
- Environment `pypi`

Create a matching `pypi` environment in the GitHub repo.

To release:

1. Bump `version` in `pyproject.toml`.
2. Publish a GitHub release named `vX.Y.Z`.
3. Update `requirements` in `../ha-vitafit-ble/custom_components/vitafit_ble/manifest.json` and that repo's dev group.

## Next steps

1. Publish v0.1.0 (see Release).
2. After a real weigh-in, add the captured frames from the owner's scale to the tests.
