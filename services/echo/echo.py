from .log import log
from util import EventLogger

evt = EventLogger()

# Simple python service to echo requests back to the caller
# Used in test
def main(x):
    log(x)
    evt.send_status("{ msg: "+ str(x) +" }")
    return x
