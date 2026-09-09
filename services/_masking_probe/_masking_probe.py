"""Services that do the wrong thing on purpose, so the exit mask can be tested.

The leading underscore keeps the directory out of describe-modules, so none of
this is mounted and none of it has a route.
"""

from util import ApolloError


def main(data_dict: dict) -> dict:
    """Reflects the payload without masking anything itself.

    Stands in for a service written by someone who did not think about it,
    which is the case the exit mask exists for.
    """
    return data_dict


def raise_with_payload(data_dict: dict) -> dict:
    """The shape nearly every service uses: catch broadly, rewrap the text."""
    try:
        raise ValueError(f"upstream rejected {data_dict.get('api_key')}")
    except ValueError as e:
        raise ApolloError(500, str(e), type="INTERNAL_ERROR") from e
