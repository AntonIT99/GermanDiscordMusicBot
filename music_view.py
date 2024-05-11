import discord

from emoji import Emoji


class MusicView(discord.ui.View):

    def __init__(self, voice_client):
        super().__init__(timeout=None)
        self.voice_client = voice_client

    @discord.ui.button(style=discord.ButtonStyle.primary, emoji=Emoji.PAUSE)
    async def play_pause(self, interaction, button):
        if self.voice_client.is_playing():
            self.voice_client.pause()
            button.emoji = Emoji.PLAY
        elif self.voice_client.is_paused():
            self.voice_client.resume()
            button.emoji = Emoji.PAUSE
        await interaction.response.edit_message(view=self)

    @discord.ui.button(style=discord.ButtonStyle.red, emoji=Emoji.STOP)
    async def stop(self, interaction, button):
        self.voice_client.stop()
        await interaction.response.defer()
