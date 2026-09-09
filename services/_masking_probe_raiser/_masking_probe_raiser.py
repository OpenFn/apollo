"""Raises with the payload in scope. Unmounted; see _masking_probe."""

from _masking_probe._masking_probe import raise_with_payload


def main(data_dict: dict) -> dict:
    return raise_with_payload(data_dict)
