import asyncio
import logging
import os
import signal
import sys
from logging.handlers import RotatingFileHandler
from random import choice

import discord
from aioconsole import ainput
from discord.ext import commands

from config import config
from helper import print_and_log, is_music_file

rfh = RotatingFileHandler(filename='bot.log', mode='a', maxBytes=1024*1024, backupCount=2, encoding='utf-8', delay=0)
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
async def on_disconnect():
    global is_connected
    is_connected = False
    print_and_log(f'{bot.user} hat Discord verlassen!', logging.INFO)


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
    Eine Umfrage erstellen (Nutzung: umfrage "Optionsname 1" "Optionsname 2" "Optionsname n")
    """
    options = [query.split("\"")[i] for i in range(1, len(query.split("\"")), 2)]
    emojis1 = ["\U0001F534", "\U000026AB", "\U000026AA", "\U0001F535", "\U0001F7E1", "\U0001F7E0", "\U0001F7E4", "\U0001F7E3", "\U0001F7E2"]
    emojis2 = ["\U0001F7EA", "\U0001F7E9", "\U0001F7E8", "\U00002B1C", "\U0001F7E5", "\U0001F7EB", "\U0001F7E7", "\U0001F7E6", "\U0001F7EB"]
    emojis = emojis1
    if len(emojis) < len(options):
        emojis += emojis2
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
    global restart_triggered
    restart_triggered = True
    await ctx.send("Wird neugestartet")
    print_and_log("Bot wird neugestartet", logging.INFO)
    await bot.close()


@bot.command()
@commands.is_owner()
async def herunterfahren(ctx):
    await ctx.send("Wird heruntergefahren")
    print_and_log("Bot wird heruntergefahren", logging.INFO)
    await bot.close()


async def admin_console_input_loop():

    while is_connected:
        try:
            # Send a message as the bot over the console by entering [channel] [message]
            admin_input = await ainput(config.get_command_prefix())
            logging.info("Konsole: {}".format(admin_input))
            channel = last_channel
            message = admin_input
            if len(admin_input.split(" ", 1)) == 2:
                channel = discord.utils.get(bot.get_all_channels(), name=admin_input.split(" ", 1)[0])
                message = admin_input.split(" ", 1)[1]
            if channel is not None:
                await channel.send(message)
            else:
                print_and_log("Keinen Kanal ausgewählt", logging.ERROR)
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
