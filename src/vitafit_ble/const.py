"""Constants for the Vitafit VT701."""

#: The scale is recognised by a local name starting with this, e.g. "Vitafit Body Fat".
LOCAL_NAME_PREFIX = "Vitafit"
MANUFACTURER = "Vitafit"
MODEL = "VT701"

NOTIFY_CHARACTERISTIC_UUID = "0000fff1-0000-1000-8000-00805f9b34fb"
WRITE_CHARACTERISTIC_UUID = "0000fff2-0000-1000-8000-00805f9b34fb"

#: Seconds to wait for a stable weight.
WEIGHT_TIMEOUT = 30.0
#: Seconds to wait for impedance after acknowledging the stable weight.
IMPEDANCE_TIMEOUT = 10.0

#: Minimum seconds between connections, so one weigh-in is read once.
POLL_INTERVAL = 60.0
#: Maximum age in seconds of an advertisement to poll for. While awake, the
#: scale advertises at least every 2 s or so.
ADVERTISEMENT_MAX_AGE = 5.0
