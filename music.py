import logging
import os
from os import listdir
from os.path import isfile, join, exists

import discord
from discord.ext import commands

from config import config
from helper import print_and_log, is_valid_url, is_music_file
from music_source import MusicSource
from music_view import create_music_view


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
        print_and_log("Sprachkanal {} beigetreten".format(channel.name), logging.INFO)

    @commands.command()
    async def listen(self, ctx, *, query=None):
        """
        Musikdateien im lokalen Dateisystem auflisten
        Nutzung: listen [Filter]
        """
        path = config.get_music_path()
        music_files = [f for f in listdir(path) if isfile(join(path, f)) and is_music_file(f)]
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
        await ctx.channel.send(response)

    @commands.command()
    async def spielen(self, ctx, *, query):
        """Musik aus dem lokalen Dateisystem abspielen oder aus einer URL herunterladen"""
        if is_valid_url(query):
            async with ctx.typing():
                source = await MusicSource.create(query, True, loop=self.bot.loop, stream=False)
                self.last_music_view = await create_music_view(ctx, source, source.content.title, self)
                await self.last_music_view.play()
        else:
            path = config.get_music_path() + os.path.sep + query
            if exists(path):
                source = await MusicSource.create(path, False, self.bot.loop)
                self.last_music_view = await create_music_view(ctx, source, query, self)
                await self.last_music_view.play()
            else:
                await ctx.send(f'{query} kann nicht gefunden werden')

    @commands.command()
    async def streamen(self, ctx, *, url):
        """Musik aus einer URL streamen"""
        async with ctx.typing():
            source = await MusicSource.create(url, True, loop=self.bot.loop, stream=True)
            self.last_music_view = await create_music_view(ctx, source, source.content.title, self)
            await self.last_music_view.play()

    @commands.command()
    async def stoppen(self, ctx):
        """Das Musikspielen aufhören"""
        if self.last_music_view is not None:
            await self.last_music_view.stop()

    @commands.command()
    async def pausieren(self, ctx):
        """Musik pausieren"""
        if self.last_music_view is not None:
            await self.last_music_view.pause()

    @commands.command()
    async def fortsetzen(self, ctx):
        """Musik fortsetzen"""
        if self.last_music_view is not None:
            await self.last_music_view.resume()

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


async def setup(bot):
    await bot.add_cog(Musik(bot))
