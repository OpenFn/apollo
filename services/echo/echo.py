from .log import log

# Simple python service to echo requests back to the caller
# Used in test
def main(x):
    log(x)
    return x
