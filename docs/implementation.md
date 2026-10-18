# Implementation

This page describes how
[`vitafit_ble.session`](https://github.com/jamesmyatt/vitafit-ble/blob/main/src/vitafit_ble/session.py)
runs a weigh-in. It describes the current code, not a stable API; see
[Protocol](protocol.md) for the exchange itself.

## Inputs

`VitafitSession.async_measure(client)` uses:

- **The client**: a `BleakClient` that's already connected to the scale.
- **The session's options**, set when the `VitafitSession` is created:
  `weight_timeout` (default 30 s), `impedance_timeout` (10 s),
  `display_unit` (none, so no unit command), `weight_only` (off) and
  `ack_every_frame` (on).
- **The session's callbacks and hooks**: frame callbacks registered with
  `register_callback`, and `on_send` and `on_receive` if a subclass overrides
  them.

The plain function `async_measure(client, session=None)` and
`async_poll(ble_device, session=None)` both run it, with a default
`VitafitSession()` if no session is given.

### Standalone

- **Client:** scan with Bleak for an advertisement that `supported()`
  recognises, then either pass its `BLEDevice` to `async_poll`, which connects
  with `bleak-retry-connector`, runs the weigh-in and disconnects, or connect a
  client yourself and call `async_measure` on it.
- **Options, callbacks and hooks:** whatever the caller sets on the session it
  creates.

`scripts/capture.py` is an example. It scans with `BleakScanner`, connects
with `bleak-retry-connector`, and runs a `RecordingSession`, which overrides
`on_send` and `on_receive` and registers a `Frame` callback to log the
exchange. Its command-line options set the session's options (`--weight-timeout`,
`--impedance-timeout`, `--unit`, `--weight-only` and `--ack-every-frame`).

### Home Assistant

The
[integration's coordinator](https://github.com/jamesmyatt/ha-vitafit-ble/blob/main/custom_components/vitafit_ble/coordinator.py)
calls `async_poll` when Home Assistant's Bluetooth integration has a recent
advertisement from the scale, `poll_needed()` is true, and a connectable
Bluetooth adapter or proxy can reach it.

- **Client:** `async_poll` connects to a `BLEDevice` from Home Assistant. That's
  the latest advertisement's, if it came through a connectable adapter or
  proxy, or otherwise the one Home Assistant's
  `async_ble_device_from_address(..., connectable=True)` finds. The connection
  may go through an ESPHome Bluetooth proxy.
- **Options:** set from the integration's configuration and entities, such as
  its weight-only mode switch. Options it doesn't set keep their defaults.
- **Callbacks and hooks:** one `WeightFrame` callback, which updates the
  real-time weight sensor with each frame. No hooks are overridden.

The result sets the weight and impedance sensors. `None` keeps the previous
weigh-in, and a `BleakError` counts as a failed poll.

## How `async_measure` runs a weigh-in

```{image} _static/async-measure-light.svg
:alt: How VitafitSession.async_measure runs a weigh-in
:class: only-light
```

```{image} _static/async-measure-dark.svg
:alt: How VitafitSession.async_measure runs a weigh-in
:class: only-dark
```

`VitafitSession.async_measure` uses three parts, which run at the same time:

- **The notification callback**, `_on_notify`, which Bleak calls for each
  notification. It decodes the frame and passes the raw bytes to
  `on_receive`. Weight and impedance frames go into the frame queue with their
  raw bytes; command replies and frames that fail their checks are dropped.
- **The main loop**, which takes frames from the frame queue in order. For each
  frame, it queues the frame's acknowledgement if needed, then runs the frame's
  callbacks, then decides whether the weigh-in has moved on: from waiting for
  a stable weight to waiting for impedance, or to the end. An optional
  acknowledgement, one that `ack_every_frame` adds, is only queued if none is
  already waiting, so a slow link can't build up a backlog. The stable
  weight's and the impedance's are always queued.
- **The ack sender**, a separate task that sends the queued acknowledgements in
  order, waiting for each write's response. It only runs while the main loop
  is waiting, so acknowledgements don't hold up the callbacks.

The weigh-in ends when an impedance frame arrives, whether or not a stable
weight came first, or when the deadline passes, however many other frames
arrive. The deadline is `weight_timeout` from the start, then
`impedance_timeout` from the stable weight. Only taking a frame is timed, and the deadline is checked before each
one, because taking from a queue that has frames in it never waits, so a
timeout alone couldn't fire while frames keep arriving.

Before returning, `async_measure` waits for the ack sender to send the
acknowledgements still queued, such as the impedance acknowledgement, so they
go out before the caller disconnects. If a write fails, its `BleakError` is
raised before the main loop takes another frame, or at the end. If anything
raises, the ack sender is cancelled, and `async_measure` waits for it to stop,
so the caller doesn't disconnect during a write; then the exception goes to
the caller.
