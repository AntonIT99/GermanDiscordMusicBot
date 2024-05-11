import logging


def print_and_log(text: str, level):
    if level == logging.CRITICAL:
        logging.critical(text)
    elif level == logging.FATAL:
        logging.fatal(text)
    elif level == logging.ERROR:
        logging.error(text)
    elif level == logging.WARNING:
        logging.warning(text)
    elif level == logging.INFO:
        logging.info(text)
    elif level == logging.DEBUG:
        logging.debug(text)
    print(text)
