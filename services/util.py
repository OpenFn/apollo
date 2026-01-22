import json
import logging
import os
import sys
import requests
import psycopg2
from dataclasses import dataclass
from typing import Optional, Any, Dict


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

    def get(self, key):
        return self._dict.get(key)

    def has(self, key):
        return key in self._dict

    def to_dict(self):
        return self._dict


@dataclass
class ApolloError(Exception):
    """Standard error class for Apollo services"""
    code: int
    message: str
    type: str = "APOLLO_ERROR"
    details: Optional[dict[str, Any]] = None

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


filename = None
loggers = {}
apollo_port = 3000


def set_log_output(f):
    """Set the output file for logging."""
    global filename

    if f is not None:
        print(f"[entry.py] writing logs to {f}")

    filename = f


def create_logger(name):
    """
    Create or retrieve a logger with the given name.
    Logs to stdout by default.
    """
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    if name not in loggers:
        logger = logging.getLogger(name)
        loggers[name] = logger
    return loggers[name]


def set_apollo_port(p):
    """Set the port for Apollo services."""
    global apollo_port
    apollo_port = p


def apollo(name, payload):
    """
    Call out to an Apollo service through HTTP.
    :param name: Name of the service.
    :param payload: Payload to send in the POST request.
    :return: JSON response.
    """
    global apollo_port
    url = f"http://127.0.0.1:{apollo_port}/services/{name}"
    r = requests.post(url, json = payload)
    return r.json()


def get_db_connection():
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
            if len(adaptor_parts) >= 3:
                self.name = "@" + adaptor_parts[1]
                self.version = adaptor_parts[2]
            else:
                raise ApolloError(
                    400,
                    f"Version must be specified in adaptor string. Expected format: '@openfn/language-http@3.1.11', got: '{adaptor_input}'",
                    type="BAD_REQUEST"
                )
        # Handle format: "http@3.1.11"
        elif len(adaptor_parts) == 2:
            self.name = f"@openfn/language-{adaptor_parts[0]}"
            self.version = adaptor_parts[1]
        else:
            raise ApolloError(
                400,
                f"Version must be specified in adaptor string. Expected format: 'http@3.1.11' or '@openfn/language-http@3.1.11', got: '{adaptor_input}'",
                type="BAD_REQUEST"
            )

    @property
    def specifier(self) -> str:
        """Full adaptor specifier: '@openfn/language-http@3.1.11'"""
        return f"{self.name}@{self.version}"

    @property
    def short_name(self) -> str:
        """Short name without @openfn/language- prefix: 'http'"""
        return self.name.split("/")[-1].replace("language-", "")


def add_page_prefix(content: str, page: Optional[dict]) -> str:
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
