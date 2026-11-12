import asyncio
import logging
import os
from typing import Optional

import discord
from discord.ext import commands

from config import config
from helper import print_and_log, is_valid_url, is_music_file, send_code_block
from music_source import MusicError, MusicSource
from music_view import MusicView

VOICE_CONNECT_TIMEOUT = 20


def list_music_files() -> list:
    """Blockierend: Musikdateien im Musikordner, alphabetisch sortiert"""
    path = config.get_music_path()
    with os.scandir(path) as entries:
        return sorted((e.name for e in entries if e.is_file() and is_music_file(e.name)), key=str.lower)


def find_music_file(query: str):
    """
    Blockierend: Datei zur Eingabe suchen. Liefert (Pfad, Kandidaten):
    exakter Name, sonst Name ohne Beachtung der Groß-/Kleinschreibung, sonst eindeutiger Namensteil.
    """
    files = list_music_files()
    path = config.get_music_path()
    if query in files:
        return os.path.join(path, query), []
    wanted = query.lower()
    matches = [f for f in files if f.lower() == wanted] or [f for f in files if wanted in f.lower()]
    if len(matches) == 1:
        return os.path.join(path, matches[0]), []
    return None, matches


class Musik(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.views = {}  # Gilden-ID -> zuletzt gestartete MusicView
        self.volumes = {}  # Gilden-ID -> zuletzt eingestellte Lautstärke (0.0 - 1.0)
        self._locks = {}

    def lock(self, guild: discord.Guild) -> asyncio.Lock:
        """Sperre pro Server, damit sich gleichzeitige Wiedergabe-Anfragen nicht überholen"""
        return self._locks.setdefault(guild.id, asyncio.Lock())

    async def ensure_voice(self, guild: discord.Guild, member=None) -> discord.VoiceClient:
        """Verbundenen VoiceClient liefern; falls nötig dem Sprachkanal des Mitglieds beitreten"""
        voice_client = guild.voice_client
        if voice_client is not None and voice_client.is_connected():
            return voice_client  # noqa
        channel = getattr(getattr(member, 'voice', None), 'channel', None)
        if channel is None:
            raise MusicError("Mit keinem Sprachkanal verbunden.")
        return await self._connect(guild, channel)

    @staticmethod
    async def _connect(guild: discord.Guild, channel) -> discord.VoiceClient:
        voice_client = guild.voice_client
        try:
            if voice_client is not None and voice_client.is_connected():
                if voice_client.channel != channel:
                    await voice_client.move_to(channel)
                return voice_client  # noqa
            if voice_client is not None:
                # Verbindung ist abgerissen: aufräumen, bevor neu verbunden wird
                await voice_client.disconnect(force=True)
            voice_client = await channel.connect(timeout=VOICE_CONNECT_TIMEOUT, reconnect=True, self_deaf=True)
        except (asyncio.TimeoutError, discord.ClientException, discord.HTTPException) as e:
            raise MusicError(f"Sprachkanal {channel.name} konnte nicht betreten werden: {e or type(e).__name__}") from e
        print_and_log("Sprachkanal {} beigetreten".format(channel.name), logging.INFO)
        return voice_client

    async def _play(self, ctx, name: str, is_url: bool, stream: bool = False):
        async with self.lock(ctx.guild):
            async with ctx.typing():
                volume = self.volumes.get(ctx.guild.id, 1.0)
                source = await MusicSource.create(name, is_url, stream, volume, notify=ctx.send)
            view = await MusicView.create(ctx, source, self)
            await view.play()

    @commands.command()
    @commands.guild_only()
    async def beitreten(self, ctx, *, channel: discord.VoiceChannel = None):
        """Einem Sprachkanal beitreten"""
        if channel is None:
            channel = getattr(ctx.author.voice, 'channel', None)
        if channel is None:
            raise MusicError("Du bist in keinem Sprachkanal. Tritt einem bei oder gib einen Kanal an.")
        await self._connect(ctx.guild, channel)

    @commands.command()
    async def listen(self, ctx, *, query=None):
        """
        Musikdateien im lokalen Dateisystem auflisten
        Nutzung: listen [Filter]
        """
        music_files = await asyncio.to_thread(list_music_files)
        if query is not None:
            music_files = [f for f in music_files if query.lower() in f.lower()]
        await send_code_block(ctx, music_files or ["Keine Ergebnisse"], header="Musikdateien:\n")

    @commands.command()
    @commands.guild_only()
    async def spielen(self, ctx, *, query):
        """Musik aus einer Datei oder einer URL abspielen"""
        if is_valid_url(query):
            await self._play(ctx, query, True, stream=False)
            return
        path, candidates = await asyncio.to_thread(find_music_file, query)
        if path is not None:
            await self._play(ctx, path, False)
        elif candidates:
            await send_code_block(ctx, candidates, header=f"'{query}' ist nicht eindeutig:\n")
        else:
            await ctx.send(f'{query} kann nicht gefunden werden')

    @commands.command()
    @commands.guild_only()
    async def streamen(self, ctx, *, url):
        """Musik aus einer URL streamen"""
        await self._play(ctx, url, True, stream=True)

    @commands.command()
    @commands.guild_only()
    async def stoppen(self, ctx):
        """Das Musikspielen aufhören"""
        view = self.views.get(ctx.guild.id)
        if view is None or not await view.stop():
            if ctx.voice_client is not None:
                ctx.voice_client.stop()

    @commands.command()
    @commands.guild_only()
    async def pausieren(self, ctx):
        """Musik pausieren"""
        view = self.views.get(ctx.guild.id)
        if view is not None:
            await view.pause()

    @commands.command()
    @commands.guild_only()
    async def fortsetzen(self, ctx):
        """Musik fortsetzen"""
        view = self.views.get(ctx.guild.id)
        if view is not None:
            await view.resume()

    @commands.command()
    @commands.guild_only()
    async def volume(self, ctx, volume: int):
        """Volume beim Musikspielen ändern (0 - 100)"""
        volume = min(max(volume, 0), 100)
        self.volumes[ctx.guild.id] = volume / 100
        view: Optional[MusicView] = self.views.get(ctx.guild.id)
        if view is not None:
            await view.set_volume(volume / 100)
        else:
            print_and_log(f"Volume wurde zu {volume}% gesetzt", logging.INFO)
        await ctx.send(f"Volume wurde zu {volume}% gesetzt")

    @commands.command()
    @commands.guild_only()
    async def verlassen(self, ctx):
        """Einen Sprachkanal verlassen"""
        if ctx.voice_client is not None:
            print_and_log(f"Verlassen des Sprachkanals {ctx.voice_client.channel.name}", logging.INFO)
            await ctx.voice_client.disconnect(force=True)

    @spielen.before_invoke
    @streamen.before_invoke
    async def ensure_voice_before_playing(self, ctx):
        await self.ensure_voice(ctx.guild, ctx.author)


async def setup(bot):
    await bot.add_cog(Musik(bot))
