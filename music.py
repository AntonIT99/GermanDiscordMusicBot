import logging
import os
from os import listdir
from os.path import isfile, join, exists

import discord
from discord.ext import commands

from config import config
from helper import print_and_log
from music_source import MusicSource
from music_view import create_music_view

music_extensions = ['.mp3', '.wav', '.ogg', '.flac', '.m4a', '.opus', '.wma', '.ac3', '.eac3', '.mp4', '.mkv', '.avi', '.mov', '.flv', '.webm', '.mpg', '.mpeg', '.ts', '.m2ts', '.wmv']


class Musik(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.last_music_view = None

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
        path = config.get_music_path() + os.path.sep + query
        if exists(path):
            source = await MusicSource.create(path, False, self.bot.loop)
            self.last_music_view = await create_music_view(ctx, source, query)
            await self.last_music_view.play()
        else:
            await ctx.send(f'{query} kann nicht gefunden werden')

    @commands.command()
    async def streamen(self, ctx, *, url):
        """Musik aus einer URL abspielen"""
        async with ctx.typing():
            source = await MusicSource.create(url, True, self.bot.loop)
            self.last_music_view = await create_music_view(ctx, source, source.content.title)
            await self.last_music_view.play()

    @commands.command()
    async def stoppen(self, ctx):
        """Das Musikspielen aufhören"""
        if self.last_music_view is not None:
            self.last_music_view.stop()

    @commands.command()
    async def pausieren(self, ctx):
        """Musik pausieren"""
        if self.last_music_view is not None:
            self.last_music_view.pause()

    @commands.command()
    async def fortsetzen(self, ctx):
        """Musik fortsetzen"""
        if self.last_music_view is not None:
            self.last_music_view.resume()

    @commands.command()
    async def volume(self, ctx, volume: int):
        """Volume beim Musikspielen ändern"""
        if ctx.voice_client is None:
            return await ctx.send("Mit keinem Sprachkanal verbunden.")

        ctx.voice_client.source.volume = volume / 100
        await ctx.send(f"Volume wurde zu {volume}% gesetzt")
        print_and_log(f"Volume wurde zu {volume}% gesetzt", logging.INFO)

    @commands.command()
    async def verlassen(self, ctx):
        """Einen Sprachkanal verlassen"""
        if ctx.voice_client is not None:
            await ctx.voice_client.disconnect()
            print_and_log(f"Verlassen des Sprachkanals {ctx.voice_client.channel.name}%", logging.INFO)

    @spielen.before_invoke
    @streamen.before_invoke
    async def ensure_voice(self, ctx):
        if ctx.voice_client is None:
            if ctx.author.voice:
                await ctx.author.voice.channel.connect()
            else:
                await ctx.send("Mit keinem Sprachkanal verbunden.")
                raise commands.CommandError("Not connected to a voice channel.")
        elif ctx.voice_client.is_playing():
            ctx.voice_client.stop()


async def setup(bot):
    await bot.add_cog(Musik(bot))
