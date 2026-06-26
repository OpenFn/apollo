from util import ApolloError
from .log import log

# Sample python service to echo requests back to the caller
def main(x):
    # raise a 400 if the payload is empty (ignoring the session id which is system-set)
    ## useful for diagnosing errors
    if not x or set(x.keys()) == {"session_id"}:
        raise ApolloError(code=400, message="payload is required", type="BAD_REQUEST")
    log(x)
    return x
