import asyncio
import logging
import os
import signal
import sys
from collections import deque
from logging.handlers import RotatingFileHandler
from random import choice

import aiofiles
import discord
from aioconsole import ainput
from discord.abc import Messageable
from discord.ext import commands

from config import config
from emoji import Emoji
from helper import print_and_log, is_music_file, parse_message_link

log_file = "bot.log"
rfh = RotatingFileHandler(filename=log_file, mode='a', maxBytes=1024*1024, backupCount=2, encoding='utf-8', delay=0)
logging.basicConfig(format='[%(asctime)s][%(levelname)s] %(message)s', encoding='utf-8', level=logging.INFO, handlers=[rfh])
bot = commands.Bot(command_prefix=commands.when_mentioned_or(config.get_command_prefix()), owner_id=config.get_owner_id(), intents=discord.Intents.all())
is_connected = False
restart_triggered = False
last_channel = None

@bot.event
async def on_ready():
    global is_connected
    is_connected = True
    print_and_log(f'{bot.user} hat sich mit Discord verbunden!', logging.INFO)
    if not is_background_process():
        asyncio.create_task(admin_console_input_loop()) # noqa
    else:
        logging.info('Keine Konsole verfügbar. Bot wird als Hintergrundprozess ausgeführt.')


@bot.event
async def on_message(message):
    global last_channel
    if message.author == bot.user:
        last_channel = message.channel
        return

    if has_word_from_list(message.content, config.get_language_list('greetings_understanding')):
        await message.channel.send(f"{choice(config.get_language_list('greetings_using'))} {message.author.mention}")
    elif has_word_from_list(message.content, config.get_language_list('farewell_understanding')):
        await message.channel.send(f"{choice(config.get_language_list('farewell_using'))} {message.author.mention}")

    if message.attachments:
        for attachment in message.attachments:
            if is_music_file(attachment.filename):
                await attachment.save(config.get_music_path() + os.path.sep + attachment.filename.replace('_', ' '))
                await message.channel.send(f"Datei '{attachment.filename.replace('_', ' ')}' hochgeladen.")
                print_and_log(f"Datei '{attachment.filename.replace('_', ' ')}' hochgeladen.", logging.INFO)

    await bot.process_commands(message)


@bot.event
async def on_command(ctx):
    channel_name = ctx.channel.name if hasattr(ctx.channel, 'name') else type(ctx.channel).__name__
    print_and_log("[{} -> {}] {} ".format(ctx.message.author, channel_name, ctx.message.content), logging.INFO)


@bot.event
async def on_member_update(before, after):
    if not after.bot and len(before.roles) == 1 and len(after.roles) > 1:
        channel = discord.utils.get(after.guild.channels, name=config.get_welcome_channel())
        await channel.send(f"Herzlich willkommen {after.mention}")


@bot.command()
async def berichten(ctx):
    """
    Verfügbarkeit des Bots testen
    """
    await ctx.channel.send(f"Zu Befehl {ctx.message.author.mention}")


@bot.command()
async def umfrage(ctx, *, query):
    """
    Eine Umfrage erstellen, z.B. umfrage "Option 1" "Option 2" "Option n"
    """
    options = [query.split("\"")[i] for i in range(1, len(query.split("\"")), 2)]
    emojis = Emoji.get_squares()
    if len(emojis) < len(options):
        emojis += Emoji.get_circles()
    text = "[Umfrage]\n"
    reactions = []
    for i in range(len(options)):
        if i < len(emojis):
            emoji = choice(emojis)
            while emoji in reactions:
                emoji = choice(emojis)
            reactions.append(emoji)
            text += options[i] + ":\t" + str(reactions[i]) + "\n"
    message = await ctx.channel.send(text)
    for i in range(len(options)):
        await message.add_reaction(reactions[i])
    print_and_log('Umfrage erstellt', logging.INFO)


@bot.command()
async def ergebnis(ctx):
    """
    Ergebnis der letzten Umfrage im Kanal
    """
    survey = None
    async for message in ctx.channel.history(limit=100):
        if "[Umfrage]" in message.content:
            survey = message
            break
    options = {survey.content.split("\n")[i].split(":\t")[1]: survey.content.split("\n")[i].split(":\t")[0] for i in range(1, len(survey.content.split("\n")))}
    results = {str(reaction): (reaction.count - 1) for reaction in survey.reactions}
    text = "[Ergebnis der letzten Umfrage]\n"
    total = 0
    for vote in results:
        total += results[vote]
    for option in options:
        percent = (results[option] / (total if total > 0 else 1)) * 100
        text += f'{option}\t{percent:.2f} %\n'
    await ctx.channel.send(text)
    print_and_log('Ergebnis der Umfrage angefordert', logging.INFO)


@bot.command()
async def hilfe(ctx):
    """
    Befehle auflisten
    """
    await ctx.send_help()


@bot.command()
@commands.is_owner()
async def neustarten(ctx):
    """
    [Admin-Befehl]
    """
    global restart_triggered
    restart_triggered = True
    print_and_log(f"{bot.user} wird neugestartet", logging.INFO)
    await ctx.send("Wird neugestartet")
    await disconnect()


@bot.command()
@commands.is_owner()
async def herunterfahren(ctx):
    """
    [Admin-Befehl]
    """
    print_and_log(f"{bot.user} wird heruntergefahren", logging.INFO)
    await ctx.send("Wird heruntergefahren")
    await disconnect()


async def disconnect():
    global is_connected
    is_connected = False
    print_and_log(f'{bot.user} hat Discord verlassen!', logging.INFO)
    await bot.change_presence(status=discord.Status.offline)
    await bot.close()


@bot.command()
@commands.is_owner()
async def loggen(ctx, lines=20):
    """
    [Admin-Befehl]
    """
    if lines < 1:
        await ctx.send("lines muss >= 1 sein.")
        return

    try:
        async with aiofiles.open(log_file, "r", encoding="utf-8") as f:
            last_lines = deque(maxlen=lines)
            async for line in f:
                last_lines.append(line)
            last_lines = list(last_lines)
    except FileNotFoundError:
        await ctx.send("Logdatei nicht gefunden.")
        return
    except OSError as e:
        await ctx.send(f"Fehler beim Lesen der Logdatei: {e}")
        return

    response = "```"
    for line in last_lines:
        if len(response) + len(line) + 3 > 2000:
            await ctx.channel.send(response + "```")
            response = "```"
        response += line
    await ctx.channel.send(response + "```")


@bot.command()
@commands.is_owner()
async def sagen(ctx, arg1, arg2=None):
    """
    [Admin-Befehl]
    """
    # Say something as the bot using syntax: sagen "[message]" [channel] or sagen "[message]"
    await say_as_bot(arg1.strip('"'), arg2, ctx)


async def say_as_bot(message, channel_name="", ctx=None):
    channel = discord.utils.get(bot.get_all_channels(), name=channel_name)
    if channel is not None and isinstance(channel, Messageable):
        await channel.send(message)
    elif last_channel is not None and isinstance(last_channel, Messageable):
        await last_channel.send(message)
    else:
        print_and_log("Kanal nicht gefunden", logging.ERROR)
        if ctx is not None:
            await ctx.channel.send("Kanal nicht gefunden")


@bot.command()
@commands.is_owner()
async def loeschen(ctx, message_ref: str, channel_name: str = None):
    """
    [Admin-Befehl]
    Löscht eine bestimmte Nachricht.

    Nutzung:
    - loeschen <message_link>
    - loeschen <message_id>
    - loeschen <message_id> <channel_name>
    """
    try:
        # Fall A: Link
        parsed = parse_message_link(message_ref)
        if parsed:
            guild_id, channel_id, message_id = parsed
            if ctx.guild is None or ctx.guild.id != guild_id:
                await ctx.send("Der Link gehört nicht zu diesem Server.")
                return

            channel = ctx.guild.get_channel(channel_id)
            if channel is None:
                await ctx.send("Kanal aus dem Link nicht gefunden.")
                return

            msg = await channel.fetch_message(message_id)
            await msg.delete()
            await ctx.send("Nachricht gelöscht.")
            return

        # Fall B: ID (+ optional Kanalname)
        message_id = int(message_ref)

        channel = None
        if channel_name:
            channel = discord.utils.get(bot.get_all_channels(), name=channel_name)
        else:
            channel = ctx.channel

        if channel is None:
            await ctx.send("Kanal nicht gefunden.")
            return

        msg = await channel.fetch_message(message_id)
        await msg.delete()
        await ctx.send("Nachricht gelöscht.")

    except discord.NotFound:
        await ctx.send("Nachricht nicht gefunden (ID/Link falsch oder zu alt/kein Zugriff).")
    except discord.Forbidden:
        await ctx.send("Keine Rechte zum Löschen (Manage Messages fehlt).")
    except ValueError:
        await ctx.send("Ungültige Message-ID. Nimm entweder einen Message-Link oder eine numerische ID.")
    except discord.HTTPException as e:
        await ctx.send(f"Fehler beim Löschen: {e}")


@bot.command()
@commands.is_owner()
async def letzte(ctx, n: int = 10, channel_name: str = None):
    """
    [Admin-Befehl]
    Zeigt die n letzten Nachrichten in einem Kanal an.

    Nutzung:
    - letzte
    - letzte 20
    - letzte 20 <channel_name>
    """
    if n < 1:
        await ctx.send("n muss >= 1 sein.")
        return
    if n > 50:
        n = 50  # sinnvoller Deckel, damit Discord nicht zugespammt wird

    channel = None
    if channel_name:
        channel = discord.utils.get(bot.get_all_channels(), name=channel_name)
    else:
        channel = ctx.channel

    if channel is None:
        await ctx.send("Kanal nicht gefunden.")
        return

    lines = []
    async for msg in channel.history(limit=n):
        ts = msg.created_at.strftime("%Y-%m-%d %H:%M:%S")
        content = msg.content.replace("```", "'''")
        if msg.attachments:
            content += " " + " ".join(a.url for a in msg.attachments)
        if not content:
            content = "<leer>"
        lines.append(f"{msg.id} | #{getattr(channel, 'name', 'DM')} | [{ts}] {msg.author}: {content}")
    lines.reverse()

    header = f"Letzte {len(lines)} Nachrichten in #{getattr(channel, 'name', 'DM')}\n"
    output = header + "\n".join(lines)

    # Discord 2000-char Limit beachten
    chunk = "```"
    for line in output.splitlines(True):
        if len(chunk) + len(line) + 3 > 2000:
            await ctx.send(chunk + "```")
            chunk = "```"
        chunk += line
    await ctx.send(chunk + "```")


async def admin_console_input_loop():
    while is_connected:
        try:
            # Send a message as the bot over the console by entering [channel] [message]
            admin_input = await ainput(config.get_command_prefix())
            logging.info("Konsole: {}".format(admin_input))
            query = admin_input.split(" ", 1)
            if len(query) == 1:
                await say_as_bot(query[0])
            elif len(query) == 2:
                await say_as_bot(query[1], query[0])
            else:
                print_and_log("Eingabe konnte nicht interpretiert werden", logging.ERROR)
        except EOFError:
            logging.error('EOFError: Eingabe konnte nicht gelesen werden')


def has_word_from_list(string, words):
    for word in words:
        if word.lower() in [s.lower() for s in string.split(" ")]:
            return True
    return False

def is_background_process():
    # Check if the environment has a TTY (interactive terminal) or if it is an IDE (IDEs have integrated consoles)
    return not sys.stdin.isatty() and not any(key in os.environ for key in ['PYCHARM_HOSTED', 'VSCODE_PID'])

def restart(signum, frame):
    os.execv(sys.executable, [sys.executable] + sys.argv)

async def main():
    async with bot:
        await bot.load_extension('music')
        await bot.start(config.get_token())
        if is_background_process():
            if restart_triggered:
                signal.signal(signal.SIGTERM, restart)
            os.kill(os.getpid(), signal.SIGTERM)
        elif restart_triggered:
            os.execv(sys.executable, [sys.executable] + sys.argv)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit()
