# Getting Started
Install python dependencies with pip:
```sh
pip install -r requirements.txt
```
Rename config.ini.example to config.ini and write your settings (bot token, etc)

Requires ffmpeg (version 5 or newer) in the PATH.

## YouTube
Music from URLs is loaded with [yt-dlp](https://github.com/yt-dlp/yt-dlp). YouTube changes often, so keep it up to date
(`.\deploy.ps1 -Reqs` reinstalls the requirements on the Raspberry Pi).

yt-dlp works best with a JavaScript runtime: [Deno](https://deno.com) or Node.js 22+ somewhere in the PATH.
Without one it still works, but only through a fallback that yt-dlp has deprecated and that offers fewer formats
(see the [yt-dlp EJS wiki](https://github.com/yt-dlp/yt-dlp/wiki/EJS)).

## Running as a service
`bot.service.example` is a systemd unit that waits for the network and restarts the bot after a crash.
`deploy.ps1` copies the current state to the Raspberry Pi and restarts the service.

Logs: `bot.log` (also via the `loggen` command) and `journalctl -u bot`.
