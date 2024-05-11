import asyncio
import logging
import os
from os import listdir
from os.path import isfile, join, exists

import discord
import youtube_dl
from discord.ext import commands

from config import config
from music_view import MusicView

music_extensions = ['.mp3', '.wav', '.ogg', '.flac', '.m4a', '.opus', '.wma', '.ac3', '.eac3', '.mp4', '.mkv', '.avi', '.mov', '.flv', '.webm', '.mpg', '.mpeg', '.ts', '.m2ts', '.wmv']

ytdl_options = {
    'format': 'bestaudio/best',
    'extractaudio': True,
    'outtmpl': '%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': False,
    'verbose': True,
    'no_warnings': False,
    'default_search': 'auto',
    'source_address': '0.0.0.0',  # bind to ipv4 since ipv6 addresses cause issues sometimes
}

ffmpeg_options = {
    # 'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5', # for ffmpeg version >= 5, does not work on ffmpeg version 4
    'options': '-vn'
}


class Musik(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def beitreten(self, ctx, *, channel: discord.VoiceChannel = None):
        """Einem Sprachkanal beitreten"""
        if channel is None:
            channel = ctx.author.voice.channel
        if ctx.voice_client is not None:
            await ctx.voice_client.move_to(channel)
        else:
            await channel.connect()
        print("Sprachkanal " + channel.name + " beigetreten")
        logging.info("Sprachkanal " + channel.name + " beigetreten")

    @commands.command()
    async def listen(self, ctx, *, query=None):
        """
        Musikdateien im lokalen Dateisystem auflisten
        Nutzung: listen [Filter]
        """
        path = config.get_music_path()
        music_files = [f for f in listdir(path) if isfile(join(path, f)) and os.path.splitext(f)[1].lower() in music_extensions]
        no_results = True
        response = "Musikdateien:\n```"
        for file in music_files:
            if query is not None:
                if query in file:
                    response += file + "\n"
                    no_results = False
            else:
                response += file + "\n"
                no_results = False
        if no_results:
            response += "Keine Ergebnisse"
        response += "```"
        await ctx.send(response)

    @commands.command()
    async def spielen(self, ctx, *, query):
        """Eine Musikdatei aus dem lokalen Dateisystem abspielen"""
        try:
            path = config.get_music_path() + os.path.sep + query
            if exists(path):
                source = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(path))
                ctx.voice_client.play(source)
                await ctx.send(f'{query} wird gespielt', view=MusicView(ctx.voice_client))
            else:
                await ctx.send(f'{query} kann nicht gefunden werden')
        except Exception as error:
            print(f'Player error: {error}')
            logging.error(f'Player error: {error}')

    @commands.command()
    async def stoppen(self, ctx):
        """Das Musikspielen aufhören"""
        if ctx.voice_client is not None:
            ctx.voice_client.stop()
            print("Musik gestoppt")
            logging.info("Musik gestoppt")

    @commands.command()
    async def streamen(self, ctx, *, url):
        """Musik aus einer URL abspielen"""
        async with ctx.typing():
            player = await YTDLSource.from_url(url, loop=self.bot.loop, stream=True)
            ctx.voice_client.play(player, after=lambda e: print(f'Player error: {e}') if e else None)

        await ctx.send(f'{player.title} wird gespielt', view=MusicView(ctx.voice_client))
        print(f'{player.title} wird gespielt')
        logging.info(f'{player.title} wird gespielt')

    @commands.command()
    async def pausieren(self, ctx):
        """Musik pausieren"""
        if ctx.voice_client.is_playing():
            ctx.voice_client.pause()

    @commands.command()
    async def fortsetzen(self, ctx):
        """Musik fortsetzen"""
        if ctx.voice_client.is_paused():
            ctx.voice_client.resume()

    @commands.command()
    async def volume(self, ctx, volume: int):
        """Volume beim Musikspielen ändern"""

        if ctx.voice_client is None:
            return await ctx.send("Zu keinem Sprachkanal verbunden.")

        ctx.voice_client.source.volume = volume / 100
        await ctx.send(f"Volume wurde zu {volume}% gesetzt")
        print(f"Volume wurde zu {volume}% gesetzt")
        logging.info("Volume wurde zu %s gesetzt", volume)

    @commands.command()
    async def verlassen(self, ctx):
        """Einen Sprachkanal verlassen"""

        if ctx.voice_client is not None:
            await ctx.voice_client.disconnect()
            print("Verlassen des Sprachkanals")
            logging.info("Verlassen des Sprachkanals")

    @spielen.before_invoke
    @streamen.before_invoke
    async def ensure_voice(self, ctx):
        if ctx.voice_client is None:
            if ctx.author.voice:
                await ctx.author.voice.channel.connect()
            else:
                await ctx.send("You are not connected to a voice channel.")
                raise commands.CommandError("Author not connected to a voice channel.")
        elif ctx.voice_client.is_playing():
            ctx.voice_client.stop()


class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)

        self.data = data

        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        ytdl = youtube_dl.YoutubeDL(ytdl_options)
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))

        if 'entries' in data:
            # take first item from a playlist
            data = data['entries'][0]

        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)


async def setup(bot):
    await bot.add_cog(Musik(bot))
