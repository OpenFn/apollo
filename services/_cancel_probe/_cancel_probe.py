"""A service that does nothing slowly, so cancellation can be tested.

The leading underscore keeps it out of describe-modules, so it is never mounted
and has no route.

It announces itself before sleeping because the spawned command is
`poetry run python ...`: the process list matches on the poetry wrapper seconds
before the interpreter has booted, so waiting on that would prove nothing.
"""

import time


def main(data_dict: dict) -> dict:
    print("EVENT:probe_started:{}", flush=True)  # noqa: T201

    seconds = data_dict.get("sleep_for", 30)
    time.sleep(seconds)

    return {"slept": seconds}
