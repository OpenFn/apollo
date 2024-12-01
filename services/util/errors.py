from dataclasses import dataclass
from typing import Optional, Any

@dataclass
class ApolloError(Exception):
    error_code: int
    error_type: str
    error_message: str
    error_details: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict:
        error_dict = {
            "errorCode": self.error_code,
            "errorType": self.error_type,
            "errorMessage": self.error_message,
        }
        if self.error_details:
            error_dict["errorDetails"] = self.error_details
        return error_dict