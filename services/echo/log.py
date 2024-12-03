from util import create_logger

logger = create_logger("echo")


def log(x):
    logger.info("Echoing request")
    logger.info(x)
