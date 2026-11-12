"""Audioquellen für den Musik-Cog: lokale Dateien sowie URLs über yt-dlp (Download oder Stream)."""
import asyncio
import io
import logging
import os
import shlex
import subprocess
import threading
import time
from collections import deque
from typing import Awaitable, Callable, Optional

import discord
import yt_dlp
from discord.ext import commands
from yt_dlp.networking import Request
from yt_dlp.networking.exceptions import HTTPError

from config import config

log = logging.getLogger(__name__)

# Maximale Wartezeit auf die ersten Audiodaten, bevor ein Startversuch als gescheitert gilt
START_TIMEOUT = 45
# YouTube gibt Stream-URLs erst nach Ablauf einer vorgeschalteten Werbung frei (davor: HTTP 403)
AVAILABILITY_MARGIN = 1
# Größe der Teilabrufe beim Streamen (1 MiB entspricht etwa einer Minute Opus-Audio)
STREAM_CHUNK_SIZE = 1024 * 1024

FFMPEG_OPTIONS = '-vn'
# Nur für ffmpeg >= 5: Verbindung bei Abbrüchen wieder aufbauen und nicht ewig auf einen toten Socket warten
FFMPEG_NETWORK_OPTIONS = ('-reconnect 1 -reconnect_streamed 1 -reconnect_on_network_error 1 '
                          '-reconnect_delay_max 5 -rw_timeout 15000000')


class MusicError(commands.CommandError):
    """Fehler mit einer Meldung, die dem Nutzer direkt angezeigt werden kann."""


class _YTDLLogger:
    """Leitet die Ausgaben von yt-dlp ins Bot-Log um (statt nur auf stdout)."""

    @staticmethod
    def debug(msg):
        if not msg.startswith('[debug] '):
            log.debug(msg)

    @staticmethod
    def info(msg):
        log.debug(msg)

    _seen_warnings = set()

    @classmethod
    def warning(cls, msg):
        # Dauerhinweise (z.B. fehlende JavaScript-Laufzeit) nur einmal als Warnung ins Log schreiben
        first_time = msg not in cls._seen_warnings
        if first_time and len(cls._seen_warnings) < 200:
            cls._seen_warnings.add(msg)
        log.log(logging.WARNING if first_time else logging.DEBUG, 'yt-dlp: %s', msg)

    @staticmethod
    def error(msg):
        log.error('yt-dlp: %s', msg)


def _ytdl_options() -> dict:
    return {
        'format': 'bestaudio/best',
        'outtmpl': '%(title)s.%(ext)s',
        'paths': {'home': config.get_music_path()},
        'restrictfilenames': True,
        'noplaylist': True,
        'ignoreerrors': False,
        'quiet': True,
        'noprogress': True,
        'logger': _YTDLLogger,
        'default_search': 'auto',
        'socket_timeout': 15,
        'retries': 5,
        'fragment_retries': 5,
        'source_address': '0.0.0.0',  # bind to ipv4 since ipv6 addresses cause issues sometimes
        # Mit einer JavaScript-Laufzeit (Deno oder Node >= 22, siehe README) stehen yt-dlp bei YouTube
        # mehr Formate zur Verfügung; fehlt sie, warnt yt-dlp nur und nutzt einen Ausweichweg.
        'js_runtimes': {'deno': {}, 'node': {}},
    }


_ytdl: Optional[yt_dlp.YoutubeDL] = None
_extract_lock = threading.Lock()  # YoutubeDL.extract_info ist nicht threadsicher


def _get_ytdl() -> yt_dlp.YoutubeDL:
    global _ytdl
    if _ytdl is None:
        _ytdl = yt_dlp.YoutubeDL(_ytdl_options())
    return _ytdl


def _extract(query: str, download: bool) -> dict:
    """Blockierend: Metadaten ermitteln und optional herunterladen."""
    with _extract_lock:
        ytdl = _get_ytdl()
        try:
            data = ytdl.extract_info(query, download=download)
        except yt_dlp.utils.DownloadError as e:
            raise MusicError(_short_ytdl_error(e)) from e
        if data is not None and 'entries' in data:
            # Suchergebnis oder Playlist: den ersten verfügbaren Eintrag nehmen
            data = next((entry for entry in data['entries'] if entry), None)
        if not data:
            raise MusicError(f"Nichts gefunden für '{query}'")
        if download:
            data['_filename'] = ytdl.prepare_filename(data)
        return data


def _seconds_until_available(data: dict) -> float:
    """
    Sekunden, bis die extrahierte URL abrufbar ist.

    Blendet YouTube vor dem Video Werbung ein, liefert die Stream-URL bis zum Ende der Werbezeit
    HTTP 403. yt-dlp meldet den Zeitpunkt als 'available_at'; wer die URL selbst abruft, muss warten.
    """
    remaining = (data.get('available_at') or 0) - time.time()
    return remaining + AVAILABILITY_MARGIN if remaining > 0 else 0.0


def _short_ytdl_error(error: Exception) -> str:
    text = str(error).strip()
    if text.startswith('ERROR: '):
        text = text[len('ERROR: '):]
    text = text.splitlines()[0] if text else type(error).__name__
    return text if len(text) <= 300 else text[:300] + '…'


class _HTTPAudioStream(io.RawIOBase):
    """
    Liest eine Mediendatei in Teilabrufen über den Netzwerk-Stack von yt-dlp.

    Gegenüber "ffmpeg öffnet die URL selbst" gehen die Abrufe damit garantiert über dieselbe IP-Familie,
    mit denselben Headern und Cookies wie die Extraktion (signierte URLs sind daran gebunden und liefern
    sonst sporadisch HTTP 403). Abgebrochene Abrufe werden an derselben Stelle fortgesetzt, eine
    abgelaufene oder abgelehnte URL wird neu ermittelt.
    """
    MAX_ATTEMPTS = 4

    def __init__(self, data: dict):
        super().__init__()
        self._ytdl = _get_ytdl()
        self._page_url = data.get('webpage_url') or data.get('original_url')
        self._format_id = data.get('format_id')
        self._url = data['url']
        self._headers = dict(data.get('http_headers') or {})
        self._data = data
        self._pos = 0
        self._size = data.get('filesize')
        self._buffer = b''
        self._response = None  # nur wenn der Server keine Teilabrufe unterstützt
        self._eof = False
        self.failed = False  # True, wenn der Stream vorzeitig abgebrochen ist

    def readable(self) -> bool:
        return True

    def read(self, size: int = -1) -> bytes:
        if self.closed:
            return b''
        if not self._buffer and not self._eof:
            try:
                self._fill()
            except Exception as e:
                log.error('Stream abgebrochen bei Byte %d: %s', self._pos, e)
                self._eof = True
                self.failed = True
        if size is None or size < 0:
            size = len(self._buffer)
        chunk, self._buffer = self._buffer[:size], self._buffer[size:]
        return chunk

    def close(self) -> None:
        self._eof = True
        self._close_response()
        super().close()

    def _close_response(self) -> None:
        if self._response is not None:
            try:
                self._response.close()
            except Exception:  # noqa
                pass
            self._response = None

    def _fill(self) -> None:
        if self._response is not None:
            self._buffer = self._response.read(64 * 1024)
            if not self._buffer:
                self._eof = True
                self._close_response()
            return
        if self._size is not None and self._pos >= self._size:
            self._eof = True
            return

        last_error: Optional[Exception] = None
        for attempt in range(self.MAX_ATTEMPTS):
            if self.closed:
                return
            if attempt:
                time.sleep(min(2 ** (attempt - 1), 4))
            try:
                self._fetch_chunk()
                return
            except HTTPError as e:
                last_error = e
                if e.status == 416:  # Bereich hinter dem Dateiende
                    self._eof = True
                    return
                log.warning('HTTP %s beim Streamen (Byte %d, Versuch %d)', e.status, self._pos, attempt + 1)
                if e.status in (401, 403, 404, 410):
                    self._refresh_url()
            except Exception as e:
                last_error = e
                log.warning('Netzwerkfehler beim Streamen (Byte %d, Versuch %d): %s', self._pos, attempt + 1, e)
        raise last_error if last_error is not None else OSError('Stream konnte nicht gelesen werden')

    def _wait_until_available(self) -> None:
        while not self.closed:
            remaining = _seconds_until_available(self._data)
            if remaining <= 0:
                return
            time.sleep(min(remaining, 0.5))

    def _fetch_chunk(self) -> None:
        self._wait_until_available()
        end = self._pos + STREAM_CHUNK_SIZE - 1
        headers = {**self._headers, 'Range': f'bytes={self._pos}-{end}'}
        response = self._ytdl.urlopen(Request(self._url, headers=headers))
        if response.status != 206:
            if self._pos:
                response.close()
                raise OSError('Server unterstützt keine Teilabrufe, Fortsetzen nicht möglich')
            # Server ignoriert Range: die Antwort fortlaufend lesen
            self._response = response
            self._buffer = response.read(64 * 1024)
            if not self._buffer:
                self._eof = True
                self._close_response()
            return
        try:
            data = response.read()
            content_range = response.headers.get('Content-Range') or ''
        finally:
            response.close()
        total = content_range.rpartition('/')[2]
        if total.isdigit():
            self._size = int(total)
        self._pos += len(data)
        self._buffer = data
        if len(data) < STREAM_CHUNK_SIZE and self._size is None:
            self._size = self._pos
        if not data:
            self._eof = True

    def _refresh_url(self) -> None:
        """Signierte URL neu ermitteln (abgelaufen oder vom Server abgelehnt)."""
        if not self._page_url or self.closed:
            return
        try:
            data = _extract(self._page_url, download=False)
        except MusicError as e:
            log.warning('Stream-URL konnte nicht erneuert werden: %s', e)
            return
        if data.get('url') and data.get('format_id') == self._format_id:
            self._url = data['url']
            self._headers = dict(data.get('http_headers') or {})
            self._data = data


class _StderrLog:
    """Sammelt die Fehlerausgabe von ffmpeg und schreibt sie ins Bot-Log."""

    def __init__(self):
        self.lines = deque(maxlen=5)
        self._partial = b''

    def write(self, data: bytes) -> None:
        *lines, self._partial = (self._partial + data).split(b'\n')
        for raw in lines:
            line = raw.decode(errors='replace').strip()
            if line:
                self.lines.append(line)
                log.warning('ffmpeg: %s', line[:300])

    def last_line(self) -> str:
        return self.lines[-1][:300] if self.lines else ''


class _FFmpegPCMAudio(discord.FFmpegPCMAudio):
    """FFmpegPCMAudio, das vor der Wiedergabe prüft, ob wirklich Audiodaten ankommen."""

    def __init__(self, source, **kwargs):
        self.stderr_log = _StderrLog()
        self.failed = False  # True, wenn die Wiedergabe durch einen Fehler endete
        self._ended = False
        self._first_frame: Optional[bytes] = None
        self._input = source if kwargs.get('pipe') else None
        super().__init__(source, stderr=self.stderr_log, **kwargs)  # noqa

    def prime(self) -> bool:
        """Blockierend: erstes Audio-Frame vorab lesen. False, wenn ffmpeg nichts liefert."""
        self._first_frame = super().read()
        if not self._first_frame:
            time.sleep(0.2)  # der Fehlerausgabe von ffmpeg Zeit geben, im Log anzukommen
        return bool(self._first_frame)

    def read(self) -> bytes:
        if self._first_frame is not None:
            frame, self._first_frame = self._first_frame, None
            return frame
        frame = super().read()
        if not frame and not self._ended:
            self._ended = True
            self._check_exit()
        return frame

    def _check_exit(self) -> None:
        """Am Ende der Daten feststellen, ob ffmpeg regulär fertig wurde oder abgebrochen ist."""
        process = getattr(self, '_process', None)
        if isinstance(process, subprocess.Popen):
            try:
                if process.wait(timeout=2) != 0:
                    self.failed = True
            except subprocess.TimeoutExpired:
                pass
        if self._input is not None and self._input.failed:
            self.failed = True

    def cleanup(self) -> None:
        if getattr(self, '_input', None) is not None:
            self._input.close()
        super().cleanup()


class MusicSource:
    """Eine abspielbare Quelle: lokale Datei oder URL (heruntergeladen oder gestreamt)."""

    def __init__(self, name: str, is_url: bool, stream: bool, title: str, audio: discord.PCMVolumeTransformer):
        self.name = name
        self.is_url = is_url
        self.stream = stream
        self.title = title
        self.audio = audio

    @property
    def volume(self) -> float:
        return self.audio.volume

    @volume.setter
    def volume(self, value: float) -> None:
        self.audio.volume = min(max(value, 0.0), 1.0)

    @property
    def failed(self) -> bool:
        """True, wenn ffmpeg die Wiedergabe mit einem Fehler abgebrochen hat."""
        return self.audio.original.failed  # noqa

    @property
    def error_detail(self) -> str:
        return self.audio.original.stderr_log.last_line()  # noqa

    def cleanup(self) -> None:
        self.audio.cleanup()

    @classmethod
    async def create(cls, name: str, is_url: bool, stream: bool = False, volume: float = 1.0,
                     notify: Optional[Callable[[str], Awaitable[None]]] = None) -> 'MusicSource':
        """
        Quelle erzeugen und prüfen, dass sie wirklich Audiodaten liefert.
        Wirft MusicError mit einer anzeigbaren Meldung, wenn alle Versuche scheitern.
        Über notify werden längere Wartezeiten gemeldet.
        """
        if not is_url:
            title = os.path.basename(name)
            try:
                audio = await cls._start(lambda: _FFmpegPCMAudio(name, options=FFMPEG_OPTIONS))
            except MusicError as e:
                detail = str(e).replace(name, title)  # den Serverpfad nicht im Chat anzeigen
                raise MusicError(f"'{title}' kann nicht abgespielt werden: {detail}") from e
            return cls(name, False, False, title, discord.PCMVolumeTransformer(audio, volume))

        loop = asyncio.get_running_loop()
        title = name
        last_error = 'kein abspielbares Format gefunden'
        data = None
        # Streamen: erst über yt-dlp geleitet, dann ffmpeg direkt, zuletzt kompletter Download
        modes = ('pipe', 'direct', 'download') if stream else ('download',)
        for mode in modes:
            if data is None or mode == 'download':
                # Nach einem gescheiterten Versuch immer frisch extrahieren (neue signierte URL)
                data = await loop.run_in_executor(None, _extract, name, mode == 'download')
                title = data.get('title') or title
            factory = cls._factory(data, mode)
            if factory is None:
                continue  # dieser Weg passt nicht zum Format; dieselben Daten für den nächsten nutzen
            wait = _seconds_until_available(data) if mode != 'download' else 0
            if wait > 0:
                log.info("'%s' ist erst in %.0f s abrufbar (Werbezeit), warte", title, wait)
                if notify is not None and wait >= 3:
                    await notify(f"'{title}' wird von der Quelle erst in {wait:.0f} Sekunden freigegeben, bitte warten …")
                await asyncio.sleep(wait)
            try:
                audio = await cls._start(factory)
            except MusicError as e:
                last_error = str(e)
                log.warning("'%s' lieferte keine Audiodaten (Weg '%s'): %s", title, mode, e)
                data = None
                continue
            if mode != modes[0]:
                log.info("'%s' wird über den Ausweichweg '%s' abgespielt", title, mode)
            return cls(name, True, stream, title, discord.PCMVolumeTransformer(audio, volume))
        raise MusicError(f"'{title}' kann nicht abgespielt werden: {last_error}")

    @staticmethod
    def _factory(data: dict, mode: str):
        """Liefert eine Funktion, die die ffmpeg-Quelle für den gewünschten Weg startet (oder None)."""
        if mode == 'download':
            filename = data['_filename']
            return lambda: _FFmpegPCMAudio(filename, options=FFMPEG_OPTIONS)
        url = data.get('url')
        if not url:
            return None
        if mode == 'pipe':
            if data.get('protocol') not in ('http', 'https'):
                return None  # z.B. HLS: das kann nur ffmpeg selbst lesen
            return lambda: _FFmpegPCMAudio(_HTTPAudioStream(data), pipe=True, options=FFMPEG_OPTIONS)
        before_options = FFMPEG_NETWORK_OPTIONS
        headers = ''.join(f'{key}: {value}\r\n' for key, value in (data.get('http_headers') or {}).items())
        if headers:
            before_options += ' -headers ' + shlex.quote(headers)
        return lambda: _FFmpegPCMAudio(url, before_options=before_options, options=FFMPEG_OPTIONS)

    @staticmethod
    async def _start(factory) -> _FFmpegPCMAudio:
        """ffmpeg starten und auf das erste Audio-Frame warten. Wirft MusicError, wenn nichts ankommt."""
        loop = asyncio.get_running_loop()
        try:
            audio = await loop.run_in_executor(None, factory)
        except discord.ClientException as e:  # z.B. ffmpeg nicht installiert
            raise MusicError(str(e)) from e
        try:
            ok = await asyncio.wait_for(loop.run_in_executor(None, audio.prime), START_TIMEOUT)
        except asyncio.TimeoutError:
            ok = False
            audio.stderr_log.lines.append('Zeitüberschreitung beim Start der Wiedergabe')
        except BaseException:
            audio.cleanup()
            raise
        if ok:
            return audio
        audio.cleanup()
        raise MusicError(audio.stderr_log.last_line() or 'keine Audiodaten erhalten')

    async def copy(self, notify: Optional[Callable[[str], Awaitable[None]]] = None) -> 'MusicSource':
        """Dieselbe Quelle neu erzeugen (für erneutes Abspielen)."""
        return await self.create(self.name, self.is_url, self.stream, self.volume, notify)
