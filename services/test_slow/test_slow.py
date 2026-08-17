"""A mounted service that does nothing slowly, so route-level cancellation can
be tested over real connections.

The bridge's own cancellation tests use the unmounted _cancel_probe and hand
run() a signal directly. That cannot see route wiring - it missed the
websocket close handler looking runs up under the wrong key - so this one is
mounted, like test_errors, and driven through a real socket.

It announces itself before sleeping because the spawned command is
`poetry run python ...`: the process list matches on the poetry wrapper
seconds before the interpreter has booted, so waiting on that would prove
nothing.
"""

import time


def main(data_dict: dict) -> dict:
    print("EVENT:probe_started:{}", flush=True)  # noqa: T201

    seconds = data_dict.get("sleep_for", 1)
    time.sleep(seconds)

    return {"slept": seconds}
