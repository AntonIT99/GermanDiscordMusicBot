import asyncio

import discord
import yt_dlp

ytdl_options = {
    'format': 'bestaudio/best',
    'extractaudio': True,
    'audioformat': 'mp3',
    'outtmpl': '%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': False,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': False,
    'no_warnings': False,
    'default_search': 'auto',
    'source_address': '0.0.0.0',  # bind to ipv4 since ipv6 addresses cause issues sometimes
}

ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5', # for ffmpeg version >= 5 only, does not work on ffmpeg version 4
    'options': '-vn'
}

ytdl = yt_dlp.YoutubeDL(ytdl_options)


class YTDLSource(discord.PCMVolumeTransformer):

    def __init__(self, audio, *, data, volume=1):
        super().__init__(audio, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))

        if 'entries' in data:
            # take first item from a playlist
            data = data['entries'][0]

        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)


class MusicSource:
    def __init__(self, name, is_url, content, loop=None, stream=True):
        self.name = name
        self.is_url = is_url
        self.content = content
        self.loop = loop
        self.stream = stream

    @classmethod
    async def create(cls, name: str, is_url: bool, loop=None, stream=True):
        content = await YTDLSource.from_url(name, loop=loop, stream=stream) if is_url else discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(name))
        return cls(name, is_url, content, loop)

    async def copy(self):
        return await self.create(self.name, self.is_url, self.loop, self.stream)
