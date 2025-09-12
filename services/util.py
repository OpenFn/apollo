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

class EventLogger:
    """
    Utility class for sending standardized event logs across services.
    This centralizes the event logging format and can be used by multiple services.
    """
    
    def __init__(self, logger=None):
        self.logger = logger
    
    def send_status(self, message: str):
        """
        Send a status update via EVENT logging
        
        :param message: Status message to log
        """
        # if self.logger:
        #     self.logger.info(f"EVENT:STATUS:{message}")
        # else:
        #     logging.info(f"EVENT:STATUS:{message}")
        ## Don't use a logger for this because we don't want to prepend the service name stuff
        print(f"EVENT:STATUS:{message}")
    
    def send_chunk(self, text: str):
        """
        Send a streaming text chunk via EVENT logging
        
        :param text: Text chunk to log
        """
        if self.logger:
            self.logger.info(f"EVENT:CHUNK:{text}")
        else:
            logging.info(f"EVENT:CHUNK:{text}")
    
    def send_code_suggestion(self, suggested_code: str, diff: Optional[Dict[str, Any]] = None):
        """
        Send code suggestion via EVENT logging
        
        :param suggested_code: The suggested code
        :param diff: Optional diff information
        """
        payload = {"suggested_code": suggested_code}
        if diff:
            payload["diff"] = diff
        
        if self.logger:
            self.logger.info(f"EVENT:CODE:{json.dumps(payload)}")
        else:
            logging.info(f"EVENT:CODE:{json.dumps(payload)}")


def create_event_logger(logger=None):
    """
    Create a new EventLogger instance with the specified logger.
    If no logger is provided, the EventLogger will use the default logger.
    
    :param logger: Optional logger instance to use for logging
    :return: An EventLogger instance
    """
    return EventLogger(logger)