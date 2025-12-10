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
        psycopg2.connection or None: Database connection if POSTGRES_URL is set, None otherwise
    """
    db_url = os.environ.get("POSTGRES_URL")
    if db_url:
        return psycopg2.connect(db_url)
    return None


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
