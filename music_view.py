import asyncio
import logging
from enum import Enum, auto

import discord

from emoji import Emoji
from helper import print_and_log
from music_source import MusicSource


async def create_music_view(ctx, source: MusicSource, title: str, music_cog):
    view = MusicView(title, ctx.channel, ctx.voice_client, source, music_cog)
    view.message = await ctx.send(f'{title} wird gespielt', view=view)
    return view

class State(Enum):
    NOT_PLAYING = auto()
    PLAYING = auto()
    PAUSED = auto()


class MusicView(discord.ui.View):

    def __init__(self, song_title: str, channel, voice_client, source: MusicSource, music_cog):
        super().__init__(timeout=None)
        self.song_title = song_title
        self.channel = channel
        self.voice_client = voice_client
        self.source = source
        self.message = None
        self.state = State.NOT_PLAYING
        self.music_cog = music_cog

    async def play(self):
        """Play the current audio source associated with this view"""
        if self.voice_client.is_connected():
            self.voice_client.stop()
            self.voice_client.play(self.source.content, after=self.on_playing_interrupted)
            print_and_log(f'{self.song_title} wird gespielt', logging.INFO)
            self.state = State.PLAYING
            self.music_cog.last_music_view = self
            asyncio.create_task(self.reset_play_button_loop()) # noqa
            await self.set_play_pause_button(Emoji.PAUSE)

    def on_playing_interrupted(self, error):
        self.state = State.NOT_PLAYING
        if error is not None:
            print_and_log(f'Fehler beim Abspielen: {error}', logging.ERROR)
        else:
            print_and_log(f'{self.song_title} ist zu Ende', logging.INFO)

    async def replay(self):
        """Regenerate the audio source and play"""
        if self.voice_client.is_connected():
            if self.source.is_url:
                async with self.channel.typing():
                    self.source = await self.source.copy()
            else:
                self.source = await self.source.copy()
            await self.play()

    async def reset_play_button_loop(self):
        """Reset the play button at the end of a song"""
        while self.state != State.NOT_PLAYING:
            await asyncio.sleep(1)
        await self.set_play_pause_button(Emoji.PLAY)

    async def pause(self):
        """Pause for this specific view"""
        if self.voice_client.is_connected() and self.voice_client.is_playing() and self.state == State.PLAYING:
            self.voice_client.pause()
            print_and_log(f'{self.song_title} wird pausiert', logging.INFO)
            self.state = State.PAUSED
            await self.set_play_pause_button(Emoji.PLAY)

    async def resume(self):
        """Resume for this specific view"""
        if self.voice_client.is_connected() and self.voice_client.is_paused() and self.state == State.PAUSED:
            self.voice_client.resume()
            print_and_log(f'{self.song_title} wird fortgesetzt', logging.INFO)
            self.state = State.PLAYING
            await self.set_play_pause_button(Emoji.PAUSE)

    async def stop(self):
        """Stop for this specific view"""
        if self.voice_client.is_connected() and self.state != State.NOT_PLAYING:
            self.voice_client.stop()
        print_and_log(f'{self.song_title} wird gestoppt', logging.INFO)

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
        if self.state == State.NOT_PLAYING:
            asyncio.create_task(self.replay()) # noqa
        elif self.state == State.PLAYING:
            asyncio.create_task(self.pause()) # noqa
        elif self.state == State.PAUSED:
            asyncio.create_task(self.resume()) # noqa
        await interaction.response.defer()

    @discord.ui.button(style=discord.ButtonStyle.red, emoji=Emoji.STOP)
    async def stop_button(self, interaction, button):
        if self.state != State.NOT_PLAYING:
            asyncio.create_task(self.stop()) # noqa
        await interaction.response.defer()

    @discord.ui.button(style=discord.ButtonStyle.secondary, emoji=Emoji.VOLUME_UP)
    async def volume_up_button(self, interaction, button):
        if self.source.content.volume + 0.2 <= 1:
            self.source.content.volume += 0.2
        else:
            self.source.content.volume = 1
        print_and_log("Volume wurde zu {:.0f}% gesetzt".format(self.source.content.volume * 100), logging.INFO)
        await interaction.response.defer()

    @discord.ui.button(style=discord.ButtonStyle.secondary, emoji=Emoji.VOLUME_DOWN)
    async def volume_down_button(self, interaction, button):
        if self.source.content.volume - 0.2 >= 0:
            self.source.content.volume -= 0.2
        else:
            self.source.content.volume = 0
        print_and_log("Volume wurde zu {:.0f}% gesetzt".format(self.source.content.volume * 100), logging.INFO)
        await interaction.response.defer()

