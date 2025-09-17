import json
import logging
import sys
import requests
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
    r = requests.post(url, payload)
    return r.json()


def send_event(name:str, message: str):
    """
    Send a generic event update via EVENT logging
    
    :param name: name/type of the event
    :param message: Status message to log
    """
    print(f"EVENT:{name}:{message}")
