# CLAUDE.md: vitafit-ble

Python library (PyPI `vitafit-ble`, MIT) for the Vitafit VT701 body fat scale. It reads weight and impedance over BLE GATT.

It is used by the Home Assistant integration in the sibling repo `../ha-vitafit-ble`. Read that repo's `CLAUDE.md` for the owner's preferences, the decisions already made and the overall next steps.

## Status (11 Oct 2026)

- v0.3.0 (`VitafitSession` with frame callbacks, plain functions instead of `VitafitBluetoothDeviceData`) released on PyPI on 11 Oct 2026 via `release.yml`, with docs at `vitafit-ble.readthedocs.io`. Renovate is enabled.
- Tested on the owner's real VT701 with `scripts/capture.py`. The frames in `tests/frames.py` are real captures.
- The Vitafit app's traffic was captured with Android HCI snoop logs, stored in a gitignored folder (`btsnoop_logs/`) because they include other devices' traffic.

## Scope and decisions

Don't revisit these without asking.

- Weight (kg) and whole-body impedance (Ω) only. No body composition or user profiles; downstream applications such as Home Assistant handle those.
- `display_unit` and `weight_only` (session options) are optional. By default no unit command is sent, so the scale keeps its display unit, and the mode command selects normal mode. The HA integration only sets the mode.
- `async_measure(client, session=None)` and `async_poll(ble_device, session=None)` take a `VitafitSession` object that the caller creates (owner's choice, 11 Oct 2026). The options are its named, keyword-only constructor arguments, so mypy checks them, and a subclass can take extra arguments because the caller constructs it. The client is passed to `VitafitSession.async_measure(client)`, not the constructor.
- No `homeassistant` imports. Use [`inkbird-ble`](https://github.com/Bluetooth-Devices/inkbird-ble) first as the template for repo structure, docs and tooling. [`oralb-ble`](https://github.com/Bluetooth-Devices/oralb-ble) is the reference for the shape of `docs/protocol.md`.
- Keep it as simple as possible (owner, 11 Oct 2026). The library holds what's specific to the scale: detection (`supported()`, `device_name()`), when to poll (`poll_needed()`), how to run a weigh-in (`VitafitSession`) and connect-measure-disconnect (`async_poll()`). These are plain functions; there's no device class or live state. Callers get live frames from callbacks registered on a `VitafitSession`. It isn't a `bluetooth-sensor-state-data` `BluetoothData`, and doesn't depend on `sensor-state-data`. `async_poll` disconnects as soon as the weigh-in ends, so other apps can use the scale.
- Protocol source: openScale [PR #1423](https://github.com/oliexdev/openScale/pull/1423) (`VitafitVT701Handler.kt`). Treat it as correct, because the owner's scale works with openScale. Real captures have extended it; `docs/protocol.md` has the frames, timing and Vitafit app findings.
- The Vitafit app also sends things the library doesn't need: the mode command repeatedly, the unit command, an ack for every weight frame, and two type `0x15` frames that look like body-composition results. Don't add or decode them.

Deliberately different from the [Bluetooth-Devices](https://github.com/Bluetooth-Devices) org patterns (owner's decisions, 6 Oct 2026):

- `uv_build`, not Poetry.
- Manual GitHub release triggers `release.yml`, with a hand-written `CHANGELOG.md` (Keep a Changelog), not python-semantic-release.
- ruff `ALL` and strict mypy.
- `requires-python >= 3.11` (the real minimum, for `asyncio.timeout`), but CI only tests 3.14, the version HA 2026.9 uses.
- No `__version__` constant; use `importlib.metadata.version("vitafit-ble")`.
- No `@retry_bluetooth_connection_error()`: the weigh-in has state (subscribe, mode and hello commands, wait, ack), so a blind retry could subscribe twice or resend the commands. `establish_connection` already retries the connection.
- Prettier comes from `rbubley/mirrors-prettier` (stable 3.x), because the org's `pre-commit/mirrors-prettier` is archived and pins a 4.0 alpha. It takes indentation from `.editorconfig`.

## Code rules

- `ImpedanceCode` is an enum because `match` needs dotted names; a bare constant in a `case` is a capture pattern. `FrameType` is an enum to type the commands (`encode_command`) and key `_DECODERS`.
- Keep "is the frame intact" (`_is_valid`: header, length byte, product ID, trailer, checksum) separate from decoding a type. Each decoder in `_DECODERS` checks its own frame length (`WEIGHT_FRAME_LENGTH`, `IMPEDANCE_FRAME_LENGTH`) and returns None if it's wrong (owner's choice, 11 Oct 2026); `decode` looks it up after `_is_valid`. Replies to the mode, hello and unit commands are valid frames that `decode` ignores.
- A failed impedance (`0xFFFF` in socks, `0x55AA` in weight-only mode, or out of range) must stay `ImpedanceFrame(impedance_ohm=None)`, not `None`. The session needs it to ack the frame and stop waiting.
- Terminology: type `0x33` is the **mode command** (openScale's first hello) and `0x44` is an unknown request, referred to as the **hello command** (the scale's reply has one data byte, `00` so far). `start_commands()` yields both, then the optional unit command.
- Log at debug level only. `async_poll` raises `BleakError` for any Bluetooth error, connecting or during the weigh-in, and returns None only if no stable weight arrives (owner approved, 11 Oct 2026). Callers such as HA's `ActiveBluetoothProcessorCoordinator` then log a run of failures once (HA's `log-when-unavailable` rule).
- `VitafitSession` keeps the weigh-in as one linear coroutine; its callbacks and `on_send`/`on_receive` hooks only observe and never drive the exchange (the ack order matters). Decoded frames use registered callbacks (`register_callback(frame_type, callback)`, dispatched along the frame class's MRO, so `Frame` callbacks run after the specific ones). Raw bytes use the overridable `on_send`/`on_receive` methods, because sent and received data are both `bytes` and can't be keyed by type. The receive hooks and callbacks run in the notification callback, not when the session takes a frame from its queue, so `scripts/capture.py` also logs frames that arrive after `async_measure` returns. `async_measure(client, session=None)` is the plain-function entry point (owner reinstated it, 11 Oct 2026); `async_poll` calls it. In docs, examples and `capture.py`, use the function only for the default weigh-in; once you have a session, call `session.async_measure(client)` (owner, 11 Oct 2026).

## Commands

```sh
uv sync                      # Python 3.11+; CI and HA use 3.14
uv run pre-commit install    # once
uv run pre-commit run --all-files   # ruff, strict mypy, prettier, codespell, pyupgrade, …
uv run pytest                # with coverage
uv run python scripts/capture.py   # log and record a real weigh-in (JSON Lines); --help for options
uv sync --group docs && uv run sphinx-build -W -b html docs docs/_build/html
uv build
```

In CI, the pre-commit hooks run on [pre-commit.ci](https://pre-commit.ci) (configured by the `ci:` block in `.pre-commit-config.yaml`), as `pre-commit/action` recommends; `.github/workflows/ci.yml` only runs the tests.

## Release

Releases are published by `.github/workflows/release.yml` when a GitHub release is published. It uses PyPI trusted publishing, so no token is needed.

To release:

1. Bump `version` in `pyproject.toml`.
2. In `CHANGELOG.md`, rename `[Unreleased]` to `[X.Y.Z] - YYYY-MM-DD`, add a new empty `[Unreleased]` section, and update the links at the bottom.
3. Publish a GitHub release named `vX.Y.Z`.
4. Update `requirements` in `../ha-vitafit-ble/custom_components/vitafit_ble/manifest.json` and that repo's `requirements_dev.txt`.
