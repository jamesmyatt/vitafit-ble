# CLAUDE.md: vitafit-ble

Python library (PyPI `vitafit-ble`, MIT) for the Vitafit VT701 body fat scale. It reads weight and impedance over BLE GATT.

It is used by the Home Assistant integration in the sibling repo `../ha-vitafit-ble`. Read that repo's `CLAUDE.md` for the owner's preferences, the decisions already made and the overall next steps.

## Status (11 Oct 2026)

- v0.4.0 (`async_poll` raises `BleakError` for a Bluetooth error during the weigh-in) released on PyPI on 12 Oct 2026 via `release.yml`, with docs at `vitafit-ble.readthedocs.io`. Renovate is enabled.
- Tested on the owner's real VT701 with `scripts/capture.py`. The frames in `tests/frames.py` are real captures.
- The Vitafit app's traffic was captured with Android HCI snoop logs, stored in a gitignored folder (`btsnoop_logs/`) because they include other devices' traffic.

## Scope and decisions

Don't revisit these without asking.

- Weight (kg) and whole-body impedance (Ω) only. No body composition or user profiles; downstream applications such as Home Assistant handle those.
- By default, also acknowledge each settling and stable weight frame that decodes, like the Vitafit app, so that the scale can replace missed or corrupt frames (owner, 16 Oct 2026). Not no-load frames: the app's HCI captures show it never acks them (owner, 19 Oct 2026). openScale acknowledges only one weight frame (the stable weight) and the impedance; `VitafitSession(ack_every_frame=False)` does the same. Captures show that acknowledging the repeated stable weight doesn't restart the impedance measurement.
- `display_unit` and `weight_only` (session options) are optional. By default no unit command is sent, so the scale keeps its display unit, and the mode command selects normal mode. The HA integration only sets the mode.
- `async_measure(client, session=None)` and `async_poll(ble_device, session=None)` take a `VitafitSession` object that the caller creates (owner's choice, 11 Oct 2026). The options are its named, keyword-only constructor arguments, so mypy checks them, and a subclass can take extra arguments because the caller constructs it. The client is passed to `VitafitSession.async_measure(client)`, not the constructor.
- No `homeassistant` imports. Use [`inkbird-ble`](https://github.com/Bluetooth-Devices/inkbird-ble) first as the template for repo structure, docs and tooling. [`oralb-ble`](https://github.com/Bluetooth-Devices/oralb-ble) is the reference for the shape of `docs/protocol.md`.
- Keep it as simple as possible (owner, 11 Oct 2026). The library holds what's specific to the scale: detection (`supported()`, `device_name()`), when to poll (`poll_needed()`), how to run a weigh-in (`VitafitSession`) and connect-measure-disconnect (`async_poll()`). These are plain functions; there's no device class or live state. Callers get live frames from callbacks registered on a `VitafitSession`. It isn't a `bluetooth-sensor-state-data` `BluetoothData`, and doesn't depend on `sensor-state-data`. `async_poll` disconnects as soon as the weigh-in ends, so other apps can use the scale.
- Protocol source: openScale [PR #1423](https://github.com/oliexdev/openScale/pull/1423) (`VitafitVT701Handler.kt`). Treat it as correct, because the owner's scale works with openScale. Real captures have extended it; `docs/protocol.md` has the frames, timing and Vitafit app findings.
- The Vitafit app also sends things the library doesn't need: the mode command repeatedly, the unit command, and two type `0x15` frames that look like body-composition results. Don't add or decode them.

Deliberately different from the [Bluetooth-Devices](https://github.com/Bluetooth-Devices) org patterns (owner's decisions, 6 Oct 2026):

- `uv_build`, not Poetry.
- Manual GitHub release triggers `release.yml`, with a hand-written `CHANGELOG.md` (Keep a Changelog), not python-semantic-release.
- ruff `ALL` and strict mypy.
- Python support policy (owner, 16 Oct 2026): supported, and tested in CI, from the Python version that the latest stable Home Assistant Core release requires (3.14 for Core 2026.10) onwards, including each new Python release. Older versions are best effort and not tested: `requires-python >= 3.12` is the code's real minimum (owner, 18 Oct 2026: PEP 695 type parameters on `register_callback` and `typing.override` in `capture.py` and the tests), and it can be raised whenever an older version stops you using a Python feature or library you want. Update the `ci.yml` matrix by hand: add each new Python release when it comes out. Keep every version in it until the owner chooses to drop it; when Core raises its Python, suggest dropping the older versions, but don't drop them unasked. Dependabot doesn't update Python versions.
- No `__version__` constant; use `importlib.metadata.version("vitafit-ble")`.
- No `@retry_bluetooth_connection_error()`: the weigh-in has state (subscribe, mode and hello commands, wait, ack), so a blind retry could subscribe twice or resend the commands. `establish_connection` already retries the connection.
- Prettier comes from `rbubley/mirrors-prettier` (stable 3.x), because the org's `pre-commit/mirrors-prettier` is archived and pins a 4.0 alpha. It takes indentation from `.editorconfig`.

## Code rules

- `ImpedanceCode` is an enum because `match` needs dotted names; a bare constant in a `case` is a capture pattern. `WeightFrame.flag` is a `WeightFlag` (no load, measuring, stable) or the raw value if unknown, like `ImpedanceCode`, and `stable` is a property worked out from it; `ack_command` builds acks from the decoded frame, echoing the flag, for the measuring and stable flags only (matched by value, so a plain `int` works too), and returns None for no load, which the app doesn't ack, or an unknown flag, as no capture shows how the scale treats it; so the session's frame queue holds only frames (owner, 18 Oct 2026). `FrameType` is an enum to type the commands (`encode_command`) and key `_DECODERS`.
- Keep "is the frame intact" (`_is_valid`: header, length byte, product ID, trailer, checksum) separate from decoding a type. Each decoder in `_DECODERS` checks its own frame length (`WEIGHT_FRAME_LENGTH`, `IMPEDANCE_FRAME_LENGTH`) and returns None if it's wrong (owner's choice, 11 Oct 2026); `decode` looks it up after `_is_valid`. Replies to the mode, hello and unit commands are valid frames that `decode` ignores.
- A failed impedance (`0xFFFF` in socks, `0x55AA` in weight-only mode, or out of range) must stay an `ImpedanceFrame` with `impedance_ohm=None`, not `None`. The session needs it to ack the frame and stop waiting. Its `code` keeps the raw value (an `ImpedanceCode` if known, otherwise the `int`), so captures show why it was skipped; `code` is None for a reading.
- Terminology: type `0x33` is the **mode command** (openScale's first hello) and `0x44` is an unknown request, referred to as the **hello command** (the scale's reply has one data byte, `00` so far). `start_commands()` yields both, then the optional unit command.
- Log at debug level only. `async_poll` raises `BleakError` for any Bluetooth error, connecting or during the weigh-in, and returns None only if no stable weight arrives, or the impedance arrives first (owner approved, 11 Oct 2026). Callers such as HA's `ActiveBluetoothProcessorCoordinator` then log a run of failures once (HA's `log-when-unavailable` rule).
- `docs/implementation.md` and its diagram describe how `async_measure` works. The diagram is hand-written SVG in two files, `docs/_static/async-measure-light.svg` and `-dark.svg`, shown by Furo's `only-light` / `only-dark` image classes so they follow the docs theme's switch (an SVG in an `<img>` can't see it); they must be identical apart from the `:root` colours, which `tests/test_docs.py` checks. Update the page and both files whenever it or a method it uses changes (`_async_start`, `_async_take_frames`, `_async_next_frame`, `_async_send_acks`, `_on_notify`, `_dispatch`, `_async_write`, `_measurement`), and render both files to check them. Its Inputs section also describes how `scripts/capture.py` and the HA coordinator build the client and session; update it when the session's options or either caller change. `docs/protocol.md` is the specification of the exchange, not the implementation (owner, 18 Oct 2026).
- `VitafitSession.async_measure` runs the weigh-in as one loop over the queue of decoded frames (owner, 16 Oct 2026): for each frame it queues the ack (every frame with `ack_every_frame`, except that an optional ack is skipped while one is already waiting in the queue, so a slow link can't build up a backlog, and when `ack_command` returns None for a no-load frame or an unknown flag (owner, 18 and 19 Oct 2026); the first stable weight's and the impedance's acks are never skipped; otherwise only the stable weight and the impedance, which are never skipped), then runs the frame's callbacks, then moves on from waiting for a stable weight to waiting for impedance, or returns. An impedance frame ends the weigh-in whenever it arrives, even before a stable weight (the result is then None), because the scale can't restart a weigh-in; it's acked, and nothing after it is (owner, 17 Oct 2026). A separate task (`_async_send_acks`) sends the queued acks in order, each a write with response, so acks don't hold up the callbacks (owner, 18 Oct 2026). Keep it simple (owner): the loop checks the task before each frame, and `async_measure` stops it with `None` and awaits it before returning, which sends the acks still queued. So a failed write's `BleakError` is raised at the next frame or the timeout, not at once. Only taking a frame from the queue is timed, against a deadline that the stable weight resets, so a timeout never interrupts a write. The weigh-in's progress (the stable `WeightFrame` and the `ImpedanceFrame`) is kept in private attributes on the session, reset in `_async_start`, and `_measurement()` builds the result from them (owner, 17 Oct 2026). They're private, so this isn't live state for callers. Its callbacks and `on_send`/`on_receive` hooks only observe and never drive the exchange (the ack order matters). Decoded frames use registered callbacks (`register_callback(frame_type, callback)`, kept in one list and run in the order registered for every frame that's an instance of their `frame_type`, so a `Frame` callback isn't moved after the specific ones (owner, 16 Oct 2026)). Raw bytes use the overridable `on_send`/`on_receive` methods, because sent and received data are both `bytes` and can't be keyed by type. `on_receive` runs in the notification callback, so `scripts/capture.py` also logs the raw bytes of frames that arrive after `async_measure` returns; the frame callbacks run in the loop, before the frame's ack is sent, so they stop when it returns, and an exception from one ends the weigh-in (owner accepted this, 17 Oct 2026; it's documented, not caught). `async_measure(client, session=None)` is the plain-function entry point (owner reinstated it, 11 Oct 2026); `async_poll` calls it. In docs, examples and `capture.py`, use the function only for the default weigh-in; once you have a session, call `session.async_measure(client)` (owner, 11 Oct 2026).

## Commands

```sh
uv sync                      # Python 3.12+; supported and tested from 3.14
uv run pre-commit install    # once
uv run pre-commit run --all-files   # ruff, strict mypy, prettier, codespell, pyupgrade, …
uv run pytest                # with coverage
uv run python scripts/capture.py   # log and record a real weigh-in (JSON Lines); --help for options
uv sync --group docs && uv run sphinx-build -W -b html docs docs/_build/html
uv build
```

In CI, the pre-commit hooks run on [pre-commit.ci](https://pre-commit.ci) (configured by the `ci:` block in `.pre-commit-config.yaml`), as `pre-commit/action` recommends; `.github/workflows/ci.yml` only runs the tests.

## Release

Releases are published by `.github/workflows/release.yml` when a GitHub release is published. It uses PyPI trusted publishing, so no token is needed, then attaches the wheel to the GitHub release with the workflow's own token.

To release:

1. Bump `version` in `pyproject.toml`.
2. In `CHANGELOG.md`, rename `[Unreleased]` to `[X.Y.Z] - YYYY-MM-DD`, add a new empty `[Unreleased]` section, and update the links at the bottom.
3. Publish a GitHub release named `vX.Y.Z`.
4. Update `requirements` in `../ha-vitafit-ble/custom_components/vitafit_ble/manifest.json` and that repo's `requirements_dev.txt`.
