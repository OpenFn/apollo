import logging
import os
import sys
from dataclasses import dataclass
from typing import Any

import psycopg2
import requests
from langfuse_util import mask_secrets

APOLLO_VERSION = os.getenv("APOLLO_VERSION", "unknown")

# Adaptor parsing constants
SCOPED_ADAPTOR_MIN_PARTS = 3
SHORTHAND_ADAPTOR_PARTS = 2

class DictObj:
    """
    A utility class that wraps a dictionary for dot-accessible attributes.
    Thanks Joel! https://joelmccune.com/python-dictionary-as-object/
    """
    def __init__(self, in_dict: dict):
        self._dict = in_dict
        assert isinstance(in_dict, dict)
        for key, val in in_dict.items():
            if isinstance(val, (list, tuple)):
                setattr(self, key, [DictObj(x) if isinstance(x, dict) else x for x in val])
            else:
                setattr(self, key, DictObj(val) if isinstance(val, dict) else val)

    def get(self, key: str) -> Any:  # noqa: ANN401
        return self._dict.get(key)

    def has(self, key: str) -> bool:
        return key in self._dict

    def to_dict(self) -> dict:
        return self._dict


@dataclass
class ApolloError(Exception):
    """Standard error class for Apollo services"""
    code: int
    message: str
    type: str = "APOLLO_ERROR"
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict:
        """Serialize the error to a dictionary format"""
        error_dict = {
            "code": self.code,
            "type": self.type,
            "message": self.message,
        }
        if self.details:
            error_dict["details"] = self.details
        return error_dict


loggers: dict[str, logging.Logger] = {}
apollo_port = 3000


class _MaskingFilter(logging.Filter):
    """Masks key-shaped values on their way out to the log stream.

    This output does not stay on the server: the bridge matches the log prefix
    on stdout and forwards the line to the caller as an SSE event. A service
    that logs its own payload would therefore hand the caller the key the
    server put there.

    Attached to the stdout handler rather than to each logger, because a
    filter on a logger only runs for records emitted through it - a plain
    `logging.getLogger(__name__)`, or a third-party logger like httpx, writes
    to the same handler and would sail past.

    Note the two levels are not equally strong. A dict is masked by field name
    and by value shape; anything already rendered to text, including a payload
    interpolated into an f-string, has only the shape to go on.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        # A container is worth masking structurally, so field names apply.
        if isinstance(record.msg, (dict, list, tuple)) and not record.args:
            record.msg = mask_secrets(record.msg)
            return True

        # Otherwise mask the text that will actually be emitted. Rendering
        # normally happens inside the handler, where a bad format string is
        # caught and reported; here it would escape into the caller's own
        # logging call, so a cosmetic typo must not fail their request.
        try:
            rendered = record.getMessage()
        except Exception:
            return True

        record.msg = mask_secrets(rendered)
        record.args = ()
        return True


_masking_filter = _MaskingFilter()


def install_log_masking() -> None:
    """Put the mask on every handler that exists right now.

    Called at import and again from create_logger, because handlers appear at
    two different times: some libraries install their own before any service
    module is imported (langfuse attaches one to the httpx logger, and it
    writes to stderr, which the bridge forwards to the caller line for line),
    and the root handler only exists once basicConfig has run.

    A filter on a handler covers every record reaching that stream whatever
    logger produced it - which a filter on a logger does not.

    loggerDict is copied rather than walked live: a thread creating a logger
    resizes it mid-walk, which raises RuntimeError.
    """
    root = logging.getLogger()
    known = [root, *(
        logger
        for logger in list(root.manager.loggerDict.values())
        if isinstance(logger, logging.Logger)
    )]

    for logger in known:
        for handler in logger.handlers:
            if _masking_filter not in handler.filters:
                handler.addFilter(_masking_filter)


def create_logger(name: str) -> logging.Logger:
    """
    Create or retrieve a logger with the given name.
    Logs to stdout by default.
    """
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    install_log_masking()

    if name not in loggers:
        loggers[name] = logging.getLogger(name)
    return loggers[name]


install_log_masking()


def set_apollo_port(p: int) -> None:
    """Set the port for Apollo services."""
    global apollo_port  # noqa: PLW0603
    apollo_port = p


def apollo(name: str, payload: dict) -> dict:
    """
    Call out to an Apollo service through HTTP.
    :param name: Name of the service.
    :param payload: Payload to send in the POST request.
    :return: JSON response.
    """
    url = f"http://127.0.0.1:{apollo_port}/services/{name}"
    # Mark internal Apollo-to-Apollo calls so they bypass instance auth (see
    # platform/src/auth/). The bridge injects the token into this child's env when
    # spawning it; absent (e.g. run standalone) the header is omitted.
    headers = {}
    internal_token = os.environ.get("APOLLO_INTERNAL_TOKEN")
    if internal_token:
        headers["X-Apollo-Internal"] = internal_token
    r = requests.post(url, json=payload, headers=headers)
    return r.json()


def get_db_connection() -> "psycopg2.extensions.connection":
    """Get database connection from POSTGRES_URL environment variable.

    Returns:
        psycopg2.connection: Database connection

    Raises:
        ApolloError: If POSTGRES_URL environment variable is not set
    """
    db_url = os.environ.get("POSTGRES_URL")
    if not db_url:
        raise ApolloError(500, "Missing POSTGRES_URL environment variable", type="DATABASE_ERROR")
    return psycopg2.connect(db_url)


def sum_usage(*usage_objects):
    """
    Sum multiple usage object token counts and return an aggregated count dictionary.

    Aggregates token counts from multiple LLM API calls (e.g., main calls, RAG pipeline calls,
    subagent calls) into a single usage dictionary.

    Args:
        *usage_objects: Variable number of usage dictionaries, each containing token count fields

    Returns:
        dict: Aggregated usage dictionary with summed token counts for:
            - cache_creation_input_tokens
            - cache_read_input_tokens
            - input_tokens
            - output_tokens

    Example:
        usage1 = {"input_tokens": 100, "output_tokens": 50}
        usage2 = {"input_tokens": 200, "output_tokens": 75}
        total = sum_usage(usage1, usage2)
        # Returns: {"input_tokens": 300, "output_tokens": 125}
    """
    result = {}

    for usage in usage_objects:
        for field in ["cache_creation_input_tokens", "cache_read_input_tokens", "input_tokens", "output_tokens"]:
            value = usage.get(field)
            if value is not None:
                result[field] = result.get(field, 0) + value

    return result


class AdaptorSpecifier:
    """
    Represents a parsed adaptor identifier.

    Accepts:
    - "@openfn/language-http@3.1.11"
    - "http@3.1.11" (shorthand)

    Provides properties:
    - name: "@openfn/language-http"
    - version: "3.1.11"
    - specifier: "@openfn/language-http@3.1.11"
    - short_name: "http"
    """

    def __init__(self, adaptor_input: str):
        """
        Parse adaptor string.

        Raises ApolloError if version is not provided.
        """
        adaptor_parts = adaptor_input.split("@")

        # Handle format: "@openfn/language-http@3.1.11"
        if adaptor_input.startswith("@"):
            if len(adaptor_parts) >= SCOPED_ADAPTOR_MIN_PARTS:
                self.name = "@" + adaptor_parts[1]
                self.version = adaptor_parts[2]
            else:
                raise ApolloError(
                    400,
                    f"Version must be specified in adaptor string. Expected format: '@openfn/language-http@3.1.11', got: '{adaptor_input}'",
                    type="BAD_REQUEST",
                )
        # Handle format: "http@3.1.11"
        elif len(adaptor_parts) == SHORTHAND_ADAPTOR_PARTS:
            self.name = f"@openfn/language-{adaptor_parts[0]}"
            self.version = adaptor_parts[1]
        else:
            raise ApolloError(
                400,
                f"Version must be specified in adaptor string. Expected format: 'http@3.1.11' or '@openfn/language-http@3.1.11', got: '{adaptor_input}'",
                type="BAD_REQUEST",
            )

    @property
    def specifier(self) -> str:
        """Full adaptor specifier: '@openfn/language-http@3.1.11'"""
        return f"{self.name}@{self.version}"

    @property
    def short_name(self) -> str:
        """Short name without @openfn/language- prefix: 'http'"""
        return self.name.split("/")[-1].replace("language-", "")


def add_page_prefix(content: str, page: dict | None) -> str:
    """
    Add [pg:...] prefix to message for page navigation tracking.

    Args:
        content: The message content to prefix
        page: Dictionary containing page metadata with optional 'type', 'name', and 'adaptor' keys

    Returns:
        The content with a [pg:type/name/adaptor] prefix if page data is present,
        otherwise returns the original content unchanged.

    Example:
        >>> add_page_prefix("Hello", {"type": "job_code", "name": "Transform", "adaptor": "http@6.5.4"})
        "[pg:job_code/Transform/http@6.5.4] Hello"
    """
    if not page:
        return content

    prefix_parts = []
    if page.get('type'):
        prefix_parts.append(str(page['type']))
    if page.get('name'):
        prefix_parts.append(str(page['name']))
    if page.get('adaptor'):
        prefix_parts.append(str(page['adaptor']))

    if not prefix_parts:
        return content

    prefix = f"[pg:{'/'.join(prefix_parts)}]"
    return f"{prefix} {content}"


# Per-attachment ceiling before the middle is dropped. Matches the adaptor-doc
# cap in job_chat: large enough for a real run log, small enough that several
# attachments can't crowd out the prompt.
ATTACHMENT_CHAR_LIMIT = 40000


def _truncate_middle(text: str, limit: int) -> str:
    """Trim `text` to `limit` chars from the middle, noting what was dropped.

    Head and tail are both kept because either end can carry the answer: a run
    log opens with the adaptor and credential it loaded and closes with the
    stack trace that killed it.
    """
    if len(text) <= limit:
        return text

    half = limit // 2
    omitted = len(text) - 2 * half
    return f"{text[:half]}\n\n[... {omitted} characters omitted ...]\n\n{text[-half:]}"


def append_attachments(content: str, attachments: list[dict] | None) -> str:
    """Append the user's input attachments to a message, verbatim.

    Attachments belong to the turn they arrived on, so callers append this to
    the message they send the model and NEVER to the history they return: a run
    log carried forward would be re-read as the current run on every later turn.
    Re-attaching per turn is the client's job.

    Each entry is a `{"type", "content"}` dict as documented in
    global_chat/PAYLOAD_SPEC.md. The type is passed through as a label rather
    than mapped to a fixed set, so a new attachment type reaches the model
    without a code change.
    """
    if not attachments:
        return content

    blocks = []
    for attachment in attachments:
        body = str(attachment.get("content") or "")
        if not body.strip():
            continue
        att_type = attachment.get("type") or "unknown"
        blocks.append(
            f'<attachment type="{att_type}">\n'
            f"{_truncate_middle(body, ATTACHMENT_CHAR_LIMIT)}\n"
            "</attachment>",
        )

    if not blocks:
        return content

    body = "\n".join(blocks)
    return (
        f"{content}\n\n"
        "<attachments>\n"
        "The user attached these to THIS message. They are the exact bytes the user "
        "sent — read them as the current evidence and quote from them rather than "
        "guessing. Attachments from earlier turns are not re-sent.\n"
        f"{body}\n"
        "</attachments>"
    )
