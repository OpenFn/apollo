"""How a typed error reaches Sentry.

Every ApolloError is captured, but they are not all the same kind of event. A
5xx is a defect; a 4xx is the caller sending something we correctly refused.
Both are worth counting, only one is worth waking someone for — so the level
separates them, and the type is a tag rather than only a field on the response,
so a search can count one kind of failure without matching message wording.
"""

import json

import pytest
import sentry_sdk
from entry import _capture_apollo_error, call
from util import ApolloError

HTTP_BAD_REQUEST = 400
HTTP_SERVICE_UNAVAILABLE = 503
OVERSIZED_CHARACTERS = 612_430
LIMIT_CHARACTERS = 250_000


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Records what would have been sent, instead of sending it."""
    events: list[dict] = []

    def fake_capture(error: BaseException, **kwargs: object) -> None:
        events.append({"error": error, **kwargs})

    monkeypatch.setattr(sentry_sdk, "capture_exception", fake_capture)
    return events


def test_a_client_error_is_searchable_but_not_alerting(captured: list[dict]) -> None:
    _capture_apollo_error(
        ApolloError(
            400,
            "Attachments are too large to analyse",
            type="ATTACHMENT_TOO_LARGE",
            details={"total_characters": OVERSIZED_CHARACTERS, "limit_characters": LIMIT_CHARACTERS},
        ),
    )

    (event,) = captured
    assert event["level"] == "warning"
    assert event["tags"]["apollo_error_type"] == "ATTACHMENT_TOO_LARGE"


def test_the_details_travel_so_the_size_can_be_read_off_the_event(captured: list[dict]) -> None:
    """Counting how often it fired is half the question; how far over is the other."""
    _capture_apollo_error(
        ApolloError(
            400,
            "Attachments are too large to analyse",
            type="ATTACHMENT_TOO_LARGE",
            details={"total_characters": OVERSIZED_CHARACTERS, "limit_characters": LIMIT_CHARACTERS},
        ),
    )

    context = captured[0]["contexts"]["apollo_error"]
    assert context["code"] == HTTP_BAD_REQUEST
    assert context["total_characters"] == OVERSIZED_CHARACTERS
    assert context["limit_characters"] == LIMIT_CHARACTERS


def test_a_server_error_still_alerts(captured: list[dict]) -> None:
    _capture_apollo_error(ApolloError(500, "boom", type="INTERNAL_ERROR"))

    assert captured[0]["level"] == "error"


def test_a_provider_failure_wearing_a_4xx_still_alerts(captured: list[dict]) -> None:
    """A 401 from Anthropic means our own key failed, which no caller can fix."""
    _capture_apollo_error(ApolloError(401, "Authentication failed", type="AUTH_ERROR"))
    _capture_apollo_error(ApolloError(429, "Rate limit exceeded", type="RATE_LIMIT"))

    assert [event["level"] for event in captured] == ["error", "error"]



def test_an_error_without_details_still_carries_its_code(captured: list[dict]) -> None:
    _capture_apollo_error(ApolloError(503, "client store unreachable", type="CLIENT_STORE_DOWN"))

    assert captured[0]["contexts"]["apollo_error"] == {"code": HTTP_SERVICE_UNAVAILABLE}


def test_a_service_raising_is_tagged_on_the_way_out(
    captured: list[dict], tmp_path: object,
) -> None:
    """The wiring, not just the helper: entry's handler must route through it."""
    path = tmp_path / "input.json"
    path.write_text(json.dumps({"api_key": "secret"}))

    call("_masking_probe_raiser", input_path=str(path))

    (event,) = captured
    assert event["tags"]["apollo_error_type"] == "INTERNAL_ERROR"
    assert event["level"] == "error"
