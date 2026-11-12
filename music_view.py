import asyncio
import logging
from enum import Enum, auto
from typing import Optional

import discord

from emoji import Emoji
from helper import print_and_log
from music_source import MusicError, MusicSource

VOLUME_STEP = 0.2


class State(Enum):
    NOT_PLAYING = auto()
    PLAYING = auto()
    PAUSED = auto()


class MusicView(discord.ui.View):
    """Nachricht mit Bedienknöpfen für genau ein Musikstück."""

    def __init__(self, music_cog, guild: discord.Guild, channel, source: MusicSource):
        super().__init__(timeout=None)
        self.music_cog = music_cog
        self.guild = guild
        self.channel = channel
        self.source = source
        self.message: Optional[discord.Message] = None
        self.state = State.NOT_PLAYING
        self._generation = 0  # unterscheidet aufeinanderfolgende Wiedergaben derselben Ansicht
        self._replaying = False
        self._tasks = set()

    @property
    def song_title(self) -> str:
        return self.source.title

    @property
    def voice_client(self) -> Optional[discord.VoiceClient]:
        # Immer den aktuellen Client der Gilde nehmen: nach einem Neuverbinden wäre ein gemerkter veraltet
        return self.guild.voice_client  # noqa

    def get_text_for_message(self) -> str:
        return "{}\n> {} {:.0f}%".format(self.song_title, Emoji.VOLUME_UP, self.source.volume * 100)

    @classmethod
    async def create(cls, ctx, source: MusicSource, music_cog) -> 'MusicView':
        view = cls(music_cog, ctx.guild, ctx.channel, source)
        view.message = await ctx.send(view.get_text_for_message(), view=view)
        return view

    async def play(self) -> bool:
        """Play the current audio source associated with this view"""
        voice_client = self.voice_client
        if voice_client is None or not voice_client.is_connected():
            self.source.cleanup()
            await self._notify("Mit keinem Sprachkanal verbunden.")
            return False

        loop = asyncio.get_running_loop()
        self._generation += 1
        generation, source = self._generation, self.source

        def after(error):
            # Läuft im Thread des Audio-Players: zurück in die Event-Loop wechseln
            loop.call_soon_threadsafe(self._on_playback_finished, generation, source, error)

        if voice_client.is_playing() or voice_client.is_paused():
            voice_client.stop()
        try:
            voice_client.play(source.audio, after=after)
        except discord.ClientException as e:
            source.cleanup()
            await self._notify(f"Wiedergabe nicht möglich: {e}")
            return False
        self.state = State.PLAYING
        self.music_cog.views[self.guild.id] = self
        print_and_log(f'{self.song_title} wird gespielt', logging.INFO)
        await self._update_message()
        return True

    def _on_playback_finished(self, generation: int, source: MusicSource, error: Optional[Exception]):
        if generation != self._generation:
            return  # diese Ansicht spielt inzwischen schon wieder etwas Neues
        self.state = State.NOT_PLAYING
        if error is not None or source.failed:
            detail = str(error) if error is not None else source.error_detail or 'ffmpeg wurde unerwartet beendet'
            print_and_log(f'Fehler beim Abspielen von {source.title}: {detail}', logging.ERROR)
            self._spawn(self._notify(f"Die Wiedergabe von '{source.title}' wurde durch einen Fehler abgebrochen."))
        else:
            print_and_log(f'{source.title} ist zu Ende', logging.INFO)
        self._spawn(self._update_message())

    async def replay(self, member: Optional[discord.Member] = None):
        """Regenerate the audio source and play"""
        if self._replaying:
            return
        self._replaying = True
        try:
            await self.music_cog.ensure_voice(self.guild, member)
            async with self.music_cog.lock(self.guild):
                async with self.channel.typing():
                    self.source = await self.source.copy(notify=self._notify)
                await self.play()
        except MusicError as e:
            await self._notify(str(e))
        finally:
            self._replaying = False

    async def pause(self) -> bool:
        """Pause for this specific view"""
        if self._pause():
            await self._update_message()
            return True
        return False

    async def resume(self) -> bool:
        """Resume for this specific view"""
        if self._resume():
            await self._update_message()
            return True
        return False

    async def stop(self) -> bool:
        """Stop for this specific view"""
        voice_client = self.voice_client
        if self.state == State.NOT_PLAYING or voice_client is None:
            return False
        print_and_log(f'{self.song_title} wird gestoppt', logging.INFO)
        voice_client.stop()  # der Knopf wird über _on_playback_finished zurückgesetzt
        return True

    async def set_volume(self, volume: float):
        self._set_volume(volume)
        await self._update_message()

    def _pause(self) -> bool:
        voice_client = self.voice_client
        if self.state == State.PLAYING and voice_client is not None and voice_client.is_playing():
            voice_client.pause()
            self.state = State.PAUSED
            print_and_log(f'{self.song_title} wird pausiert', logging.INFO)
            return True
        return False

    def _resume(self) -> bool:
        voice_client = self.voice_client
        if self.state == State.PAUSED and voice_client is not None and voice_client.is_paused():
            voice_client.resume()
            self.state = State.PLAYING
            print_and_log(f'{self.song_title} wird fortgesetzt', logging.INFO)
            return True
        return False

    def _set_volume(self, volume: float):
        self.source.volume = round(volume, 2)
        # Für die nächsten Stücke auf diesem Server merken
        self.music_cog.volumes[self.guild.id] = self.source.volume
        print_and_log("Volume wurde zu {:.0f}% gesetzt".format(self.source.volume * 100), logging.INFO)

    def _sync_button(self):
        self.play_pause_button.emoji = Emoji.PAUSE if self.state == State.PLAYING else Emoji.PLAY

    async def _update_message(self):
        """Text und Knöpfe der Nachricht an den aktuellen Zustand anpassen"""
        if self.message is None:
            return
        self._sync_button()
        try:
            await self.message.edit(content=self.get_text_for_message(), view=self)
        except discord.HTTPException as e:  # z.B. Nachricht wurde gelöscht
            logging.debug("Musik-Nachricht konnte nicht aktualisiert werden: %s", e)

    async def _respond(self, interaction: discord.Interaction):
        """Knopfdruck bestätigen und dabei die Nachricht in einem Schritt aktualisieren"""
        self._sync_button()
        try:
            await interaction.response.edit_message(content=self.get_text_for_message(), view=self)
        except discord.HTTPException as e:
            logging.debug("Interaktion konnte nicht beantwortet werden: %s", e)

    async def _notify(self, text: str):
        try:
            await self.channel.send(text)
        except discord.HTTPException as e:
            logging.warning("Nachricht konnte nicht gesendet werden: %s", e)

    def _spawn(self, coro):
        # Referenz halten, sonst kann die Task vom Garbage Collector vorzeitig entfernt werden
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def on_error(self, interaction: discord.Interaction, error: Exception, item):
        logging.error("Fehler bei Knopfdruck %s", getattr(item, 'emoji', item), exc_info=error)

    @discord.ui.button(style=discord.ButtonStyle.primary, emoji=Emoji.PAUSE)
    async def play_pause_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.state == State.NOT_PLAYING:
            await interaction.response.defer()
            await self.replay(interaction.user)
            return
        if self.state == State.PLAYING:
            self._pause()
        else:
            self._resume()
        await self._respond(interaction)

    @discord.ui.button(style=discord.ButtonStyle.red, emoji=Emoji.STOP)
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await self.stop()

    @discord.ui.button(style=discord.ButtonStyle.secondary, emoji=Emoji.VOLUME_UP)
    async def volume_up_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self._set_volume(self.source.volume + VOLUME_STEP)
        await self._respond(interaction)

    @discord.ui.button(style=discord.ButtonStyle.secondary, emoji=Emoji.VOLUME_DOWN)
    async def volume_down_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self._set_volume(self.source.volume - VOLUME_STEP)
        await self._respond(interaction)
