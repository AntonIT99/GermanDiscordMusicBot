import asyncio
import logging
import sys
from random import choice

import discord
from aioconsole import ainput
from discord.ext import commands

from config import Config

logging.basicConfig(format='[%(asctime)s][%(levelname)s] %(message)s', filename='bot.log', encoding='utf-8', level=logging.INFO)
config = Config()
bot = commands.Bot(command_prefix=commands.when_mentioned_or(config.get_command_prefix()), intents=discord.Intents.all())


@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')
    logging.info(f'{bot.user} has connected to Discord!')
    while True:
        admin_input = await ainput("+")
        if len(admin_input.split(" ", 1)) == 2:
            channel = discord.utils.get(bot.get_all_channels(), name=admin_input.split(" ", 1)[0])
            await channel.send(admin_input.split(" ", 1)[1])


@bot.event
async def on_message(message):
    if not message.author.bot:
        if has_word_from_list(message.content, config.get_language_list('greetings_understanding')):
            await message.channel.send(f"{choice(config.get_language_list('greetings_using'))} {message.author.mention}")
        elif has_word_from_list(message.content, config.get_language_list('farewell_understanding')):
            await message.channel.send(f"{choice(config.get_language_list('farewell_using'))} {message.author.mention}")
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
    print('Umfrage erstellt')
    logging.info('Umfrage erstellt')


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
    print('Ergebnis der Umfrage angefordert')
    logging.info('Ergebnis der Umfrage angefordert')


@bot.command()
async def hilfe(ctx):
    """
    Befehle auflisten
    """
    await ctx.send_help()


def has_word_from_list(string, words):
    for word in words:
        if word.lower() in [s.lower() for s in string.split(" ")]:
            return True
    return False


async def main():
    async with bot:
        await bot.load_extension('music')
        await bot.start(config.get_token())

try:
    asyncio.run(main())
except KeyboardInterrupt:
    sys.exit()