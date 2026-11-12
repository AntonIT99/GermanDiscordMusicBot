import logging
import os
import re
from functools import lru_cache

from urllib.parse import urlparse

music_extensions = {'.mp3', '.wav', '.ogg', '.flac', '.m4a', '.opus', '.wma', '.ac3', '.eac3', '.mp4', '.mkv', '.avi', '.mov', '.flv', '.webm', '.mpg', '.mpeg', '.ts', '.m2ts', '.wmv'}

MESSAGE_LINK_RE = re.compile(r"https?://(?:ptb\.|canary\.)?discord(?:app)?\.com/channels/(\d+)/(\d+)/(\d+)$")

DISCORD_MESSAGE_LIMIT = 2000


def parse_message_link(link: str):
    m = MESSAGE_LINK_RE.match(link.strip("<> "))
    if not m:
        return None
    guild_id, channel_id, message_id = map(int, m.groups())
    return guild_id, channel_id, message_id


def print_and_log(text: str, level):
    logging.log(level, text)
    # flush: als Dienst ist stdout gepuffert, die Zeilen kämen sonst stark verzögert im Journal an
    print(text, flush=True)


def is_valid_url(url) -> bool:
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])  # Check if both scheme and netloc are present
    except ValueError:
        return False


def is_music_file(filename) -> bool:
    return os.path.splitext(filename)[1].lower() in music_extensions


@lru_cache(maxsize=16)
def _phrase_pattern(phrases: tuple):
    # Längere Ausdrücke zuerst, damit "Guten Morgen" vor "Guten" greift
    alternatives = "|".join(re.escape(p) for p in sorted(phrases, key=len, reverse=True) if p)
    return re.compile(rf"(?<!\w)(?:{alternatives})(?!\w)", re.IGNORECASE) if alternatives else None


def has_phrase_from_list(text: str, phrases) -> bool:
    """Prüft, ob einer der Ausdrücke (auch mehrere Wörter) als ganzes Wort im Text vorkommt"""
    pattern = _phrase_pattern(tuple(phrases))
    return pattern is not None and pattern.search(text) is not None


def tail_lines(path: str, count: int) -> list:
    """Blockierend: die letzten Zeilen einer Textdatei lesen, ohne die ganze Datei zu laden"""
    block_size = 64 * 1024
    data = b""
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        position = f.tell()
        while position > 0 and data.count(b"\n") <= count:
            step = min(block_size, position)
            position -= step
            f.seek(position)
            data = f.read(step) + data
    return data.decode("utf-8", errors="replace").splitlines()[-count:]


async def send_code_block(destination, lines, header: str = ""):
    """Zeilen als Codeblock senden, bei Bedarf auf mehrere Nachrichten verteilt (Discord-Limit)"""
    fence = "```"
    max_line = DISCORD_MESSAGE_LIMIT - 2 * len(fence) - 2
    chunk = header + fence + "\n"
    has_content = False
    for line in lines:
        line = line.rstrip("\r\n").replace(fence, "'''")
        for start in range(0, max(len(line), 1), max_line):
            part = line[start:start + max_line]
            if has_content and len(chunk) + len(part) + 1 + len(fence) > DISCORD_MESSAGE_LIMIT:
                await destination.send(chunk + fence)
                chunk = fence + "\n"
            chunk += part + "\n"
            has_content = True
    await destination.send(chunk + fence)
