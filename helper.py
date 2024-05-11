import logging
import os

from urllib.parse import urlparse

music_extensions = ['.mp3', '.wav', '.ogg', '.flac', '.m4a', '.opus', '.wma', '.ac3', '.eac3', '.mp4', '.mkv', '.avi', '.mov', '.flv', '.webm', '.mpg', '.mpeg', '.ts', '.m2ts', '.wmv']

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


def is_valid_url(url) -> bool:
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])  # Check if both scheme and netloc are present
    except ValueError:
        return False

def is_music_file(filename) -> bool:
    return os.path.splitext(filename)[1].lower() in music_extensions