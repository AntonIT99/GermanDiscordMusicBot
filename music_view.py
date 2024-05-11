import asyncio
import logging

import discord

from emoji import Emoji
from helper import print_and_log
from music_source import MusicSource


async def create_music_view(ctx, source: MusicSource, title: str):
    view = MusicView(title, ctx.channel, ctx.voice_client, source)
    view.message = await ctx.send(f'{title} wird gespielt', view=view)
    return view


class MusicView(discord.ui.View):

    def __init__(self, song_title: str, channel, voice_client, source: MusicSource):
        super().__init__(timeout=None)
        self.song_title = song_title
        self.channel = channel
        self.voice_client = voice_client
        self.source = source
        self.message = None
        self.is_playing = False

    async def play(self):
        self.is_playing = True
        self.voice_client.play(self.source.content, after=self.on_playing_interrupted)
        asyncio.create_task(self.loop())
        print_and_log(f'{self.song_title} wird gespielt', logging.INFO)
        await self.set_play_pause_button(Emoji.PAUSE)

    async def loop(self):
        while self.is_playing:
            await asyncio.sleep(1)
        await self.set_play_pause_button(Emoji.PLAY)

    async def replay(self):
        self.source = await self.source.copy()
        await self.play()

    async def pause(self):
        if self.voice_client.is_playing():
            self.voice_client.pause()
            print_and_log(f'{self.song_title} wird pausiert', logging.INFO)
        await self.set_play_pause_button(Emoji.PLAY)

    async def resume(self):
        if self.voice_client.is_paused():
            self.voice_client.resume()
            print_and_log(f'{self.song_title} wird fortgesetzt', logging.INFO)
        await self.set_play_pause_button(Emoji.PAUSE)

    async def stop(self):
        self.voice_client.stop()
        print_and_log(f'{self.song_title} wird gestoppt', logging.INFO)

    def on_playing_interrupted(self, error):
        self.is_playing = False
        if error is not None:
            print_and_log(f'Fehler beim Abspielen: {error}', logging.ERROR)
        else:
            print_and_log(f'{self.song_title} ist zu Ende', logging.INFO)

    async def set_play_pause_button(self, emoji: str):
        if self.message is not None:
            play_pause_button = self.__get_play_pause_button()
            if play_pause_button is not None and play_pause_button.emoji.name != emoji:
                play_pause_button.emoji.name = emoji
                await self.message.edit(view=self)

    def __get_play_pause_button(self):
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                if item.emoji.name == Emoji.PAUSE or item.emoji.name == Emoji.PLAY:
                    return item
        return None

    @discord.ui.button(style=discord.ButtonStyle.primary, emoji=Emoji.PAUSE)
    async def play_pause_button(self, interaction, button):
        if self.voice_client.is_playing():
            await self.pause()
        elif self.voice_client.is_paused():
            await self.resume()
        elif self.voice_client.is_connected():
            await self.replay()
        await interaction.response.defer()

    @discord.ui.button(style=discord.ButtonStyle.red, emoji=Emoji.STOP)
    async def stop_button(self, interaction, button):
        await self.stop()
        await interaction.response.defer()
