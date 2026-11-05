"""A service that makes an apollo() self-call, so the fork-IPC round-trip can
be tested end to end.

Leading underscore keeps it out of describe-modules, so it is never mounted.
In a forked child, apollo() rides the request socket: this service emits a
CALL line, the bridge runs the named service and writes a REPLY line back, and
the result is returned here.
"""

from util import apollo


def main(data: dict) -> dict:
    service = data.get("service", "echo")
    payload = data.get("payload", {})
    reply = apollo(service, payload)
    return {"got": reply}
