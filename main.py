import asyncio
import logging
import os
import signal
import sys
from logging.handlers import RotatingFileHandler
from random import choice, sample

import discord
from aioconsole import ainput
from discord.abc import Messageable
from discord.ext import commands

from config import config
from emoji import Emoji
from helper import print_and_log, is_music_file, parse_message_link, has_phrase_from_list, tail_lines, send_code_block

log_file = "bot.log"
MAX_LOG_LINES = 300


class ReconnectNoiseFilter(logging.Filter):
    """
    Kürzt die Meldungen von discord.py bei Verbindungsabbrüchen auf eine Zeile.
    Ohne Internet (z.B. nächtliche Zwangstrennung) füllte sonst jeder Versuch das Log mit einem kompletten Traceback.
    """

    def filter(self, record):
        if record.name == 'discord.client' and record.exc_info and str(record.msg).startswith('Attempting a reconnect'):
            error = record.exc_info[1]
            record.msg = f"{record.getMessage()} ({type(error).__name__}: {error})"
            record.args = None
            record.exc_info = None
            record.exc_text = None
        return True


rfh = RotatingFileHandler(filename=log_file, mode='a', maxBytes=1024*1024, backupCount=2, encoding='utf-8', delay=0)
rfh.addFilter(ReconnectNoiseFilter())
logging.basicConfig(format='[%(asctime)s][%(levelname)s] %(message)s', encoding='utf-8', level=logging.INFO, handlers=[rfh])

# Nur die Ereignisse abonnieren, die der Bot braucht. Intents.all() enthält u.a. Presence-Updates
# aller Mitglieder, die auf dem Raspberry Pi unnötig Rechenzeit und Bandbreite kosten.
intents = discord.Intents.default()
intents.members = True  # on_member_update (Begrüßung bei Rollenvergabe)
intents.message_content = True  # Befehle und Grußerkennung
bot = commands.Bot(command_prefix=commands.when_mentioned_or(config.get_command_prefix()), owner_id=config.get_owner_id(), intents=intents)
is_connected = False
restart_triggered = False
last_channel = None
console_task = None

@bot.event
async def on_ready():
    global is_connected, console_task
    first_time = not is_connected
    is_connected = True
    print_and_log(f'{bot.user} hat sich mit Discord verbunden!', logging.INFO)
    # on_ready kann mehrfach kommen (nach jeder neu aufgebauten Sitzung): Konsole nur einmal starten
    if is_background_process():
        if first_time:
            logging.info('Keine Konsole verfügbar. Bot wird als Hintergrundprozess ausgeführt.')
    elif console_task is None or console_task.done():
        console_task = asyncio.create_task(admin_console_input_loop())


@bot.event
async def on_message(message):
    global last_channel
    if message.author == bot.user:
        last_channel = message.channel
        return

    if message.author.bot:
        return  # anderen Bots weder antworten noch gehorchen (sonst drohen Endlosschleifen)

    if has_phrase_from_list(message.content, config.get_language_list('greetings_understanding')):
        await message.channel.send(f"{choice(config.get_language_list('greetings_using'))} {message.author.mention}")
    elif has_phrase_from_list(message.content, config.get_language_list('farewell_understanding')):
        await message.channel.send(f"{choice(config.get_language_list('farewell_using'))} {message.author.mention}")

    for attachment in message.attachments:
        if is_music_file(attachment.filename):
            await save_music_attachment(message, attachment)

    await bot.process_commands(message)


async def save_music_attachment(message, attachment):
    # basename: der Dateiname kommt vom Nutzer und darf nicht aus dem Musikordner hinausführen
    filename = os.path.basename(attachment.filename.replace('_', ' '))
    try:
        await attachment.save(os.path.join(config.get_music_path(), filename))
    except (discord.HTTPException, OSError) as e:
        print_and_log(f"Datei '{filename}' konnte nicht gespeichert werden: {e}", logging.ERROR)
        await message.channel.send(f"Datei '{filename}' konnte nicht gespeichert werden.")
        return
    await message.channel.send(f"Datei '{filename}' hochgeladen.")
    print_and_log(f"Datei '{filename}' hochgeladen.", logging.INFO)


@bot.event
async def on_command(ctx):
    channel_name = ctx.channel.name if hasattr(ctx.channel, 'name') else type(ctx.channel).__name__
    print_and_log("[{} -> {}] {} ".format(ctx.message.author, channel_name, ctx.message.content), logging.INFO)


@bot.event
async def on_command_error(ctx, error):
    """Fehler dem Nutzer melden, statt sie nur im Log zu vergraben"""
    if isinstance(error, commands.CommandNotFound):
        return  # z.B. "+1" im Chat: kein Befehl, also still bleiben
    original = getattr(error, 'original', error)
    command = ctx.command.qualified_name if ctx.command else '?'
    if isinstance(error, commands.NotOwner):
        text = "Dieser Befehl ist dem Besitzer des Bots vorbehalten."
    elif isinstance(error, commands.NoPrivateMessage):
        text = "Dieser Befehl funktioniert nur auf einem Server."
    elif isinstance(error, commands.UserInputError):
        usage = f"{config.get_command_prefix()}{command} {ctx.command.signature}".strip()
        text = f"Falsche Eingabe: {error}\nNutzung: `{usage}`"
    elif isinstance(original, discord.Forbidden):
        text = "Dafür fehlen mir die Rechte."
    elif isinstance(error, commands.CommandInvokeError):
        logging.error("Fehler im Befehl %s", command, exc_info=original)
        text = f"Unerwarteter Fehler im Befehl {command}: {type(original).__name__}: {original}"
    else:
        # MusicError, fehlgeschlagene Checks usw. bringen eine anzeigbare Meldung mit
        text = str(error) or type(error).__name__
    print_and_log(f"Befehl {command} fehlgeschlagen: {text}", logging.WARNING)
    try:
        await ctx.send(text[:2000])
    except discord.HTTPException:
        pass


@bot.event
async def on_member_update(before, after):
    if not after.bot and len(before.roles) == 1 and len(after.roles) > 1:
        # Nicht jeder Server hat den Willkommenskanal
        channel = discord.utils.get(after.guild.text_channels, name=config.get_welcome_channel())
        if channel is not None:
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
    options = query.split("\"")[1::2]
    emojis = Emoji.get_squares()
    if len(emojis) < len(options):
        emojis += Emoji.get_circles()
    if not options or len(options) > len(emojis):
        await ctx.send(f"Bitte 1 bis {len(emojis)} Optionen in Anführungszeichen angeben, z.B. umfrage \"Option 1\" \"Option 2\"")
        return
    reactions = sample(emojis, len(options))
    text = "[Umfrage]\n" + "".join(f"{option}:\t{reaction}\n" for option, reaction in zip(options, reactions))
    message = await ctx.channel.send(text)
    for reaction in reactions:
        await message.add_reaction(reaction)
    print_and_log('Umfrage erstellt', logging.INFO)


@bot.command()
async def ergebnis(ctx):
    """
    Ergebnis der letzten Umfrage im Kanal
    """
    survey = None
    async for message in ctx.channel.history(limit=100):
        if message.author == bot.user and message.content.startswith("[Umfrage]"):
            survey = message
            break
    if survey is None:
        await ctx.send("Keine Umfrage in den letzten 100 Nachrichten gefunden.")
        return
    # Zeilen der Umfrage: "<Option>:\t<Emoji>"
    options = {}
    for line in survey.content.split("\n")[1:]:
        name, separator, emoji = line.rpartition(":\t")
        if separator:
            options[emoji.strip()] = name
    # Die eigene Reaktion des Bots zählt nicht als Stimme
    results = {str(reaction.emoji): reaction.count - (1 if reaction.me else 0) for reaction in survey.reactions}
    total = sum(results.get(emoji, 0) for emoji in options)
    text = "[Ergebnis der letzten Umfrage]\n"
    for emoji in options:
        percent = (results.get(emoji, 0) / (total if total > 0 else 1)) * 100
        text += f'{options[emoji]}:\t{emoji}\t{percent:.2f} %\n'
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
    lines = min(lines, MAX_LOG_LINES)  # sinnvoller Deckel, damit Discord nicht zugespammt wird

    try:
        last_lines = await asyncio.to_thread(tail_lines, log_file, lines)
    except FileNotFoundError:
        await ctx.send("Logdatei nicht gefunden.")
        return
    except OSError as e:
        await ctx.send(f"Fehler beim Lesen der Logdatei: {e}")
        return

    await send_code_block(ctx.channel, last_lines or ["<leer>"])


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
        content = msg.content
        if msg.attachments:
            content += " " + " ".join(a.url for a in msg.attachments)
        if not content:
            content = "<leer>"
        lines.append(f"{msg.id} | #{getattr(channel, 'name', 'DM')} | [{ts}] {msg.author}: {content}")
    lines.reverse()

    header = f"Letzte {len(lines)} Nachrichten in #{getattr(channel, 'name', 'DM')}"
    output = header + "\n" + "\n".join(lines)

    # Discord 2000-char Limit beachten
    await send_code_block(ctx, output.splitlines())


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
