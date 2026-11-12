"""
Kleines Kommandozeilen-Werkzeug, um mit dem Bot-Account per REST auf Discord zuzugreifen
(Server/Kanäle auflisten, Nachrichten lesen, Anhänge herunterladen).

Es nutzt nur die REST-API und öffnet keine Gateway-Verbindung, stört den laufenden Bot also nicht.
Der Token kommt wie beim Bot aus config.ini. Alle Befehle sind rein lesend.

Beispiele:
    python discord_tool.py guilds
    python discord_tool.py channels
    python discord_tool.py messages allgemein --limit 50
    python discord_tool.py download bilder --limit 200 --ext png
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from config import config

API = 'https://discord.com/api/v10'
USER_AGENT = 'DiscordBot (https://github.com/Rapptz/discord.py, 2.0) NazarickBot-tool'
# Nur von diesen Hosts werden Anhänge geladen (Embeds können beliebige fremde URLs enthalten).
CDN_HOSTS = ('cdn.discordapp.com', 'media.discordapp.net')
TEXT_CHANNEL_TYPES = {0: 'text', 2: 'voice', 5: 'news', 10: 'thread', 11: 'thread', 12: 'thread', 13: 'stage', 15: 'forum', 16: 'media'}


def api(path, params=None):
    url = API + path
    if params:
        url += '?' + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    request = urllib.request.Request(url, headers={'Authorization': 'Bot ' + config.get_token(), 'User-Agent': USER_AGENT})
    for _ in range(5):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8', 'replace')
            if e.code == 429:
                try:
                    delay = float(json.loads(body).get('retry_after', 1))
                except ValueError:
                    delay = 1.0
                time.sleep(delay + 0.1)
                continue
            sys.exit(f'Discord API {e.code} für {path}: {body}')
    sys.exit(f'Discord API: zu viele Rate-Limits für {path}')


def get_guilds():
    return api('/users/@me/guilds')


def get_channels(guild_id):
    channels = api(f'/guilds/{guild_id}/channels')
    channels += api(f'/guilds/{guild_id}/threads/active').get('threads', [])
    return channels


def resolve_guild(value):
    guilds = get_guilds()
    if value is None:
        if len(guilds) == 1:
            return guilds[0]
        sys.exit('Mehrere Server, bitte --guild angeben: ' + ', '.join(f"{g['name']} ({g['id']})" for g in guilds))
    for guild in guilds:
        if guild['id'] == value or guild['name'].lower() == value.lower():
            return guild
    sys.exit(f'Server nicht gefunden: {value}')


def resolve_channel(value, guild_value):
    """Kanal-ID direkt verwenden, sonst den Namen (mit oder ohne #) im Server suchen."""
    if value.isdigit():
        return value
    name = value.lstrip('#').lower()
    guild = resolve_guild(guild_value)
    matches = [c for c in get_channels(guild['id']) if c.get('name', '').lower() == name]
    if not matches:
        sys.exit(f"Kanal '{value}' nicht gefunden in {guild['name']}")
    if len(matches) > 1:
        # Gleichnamige Sprach- und Textkanäle sind üblich: dann ist der Textkanal gemeint
        matches = [c for c in matches if c['type'] == 0] or matches
    if len(matches) > 1:
        sys.exit('Mehrere Kanäle mit diesem Namen, bitte ID verwenden: ' + ', '.join(c['id'] for c in matches))
    return matches[0]['id']


def fetch_messages(channel_id, limit, before=None, after=None):
    """Liefert bis zu `limit` Nachrichten, neueste zuerst (mit `after`: älteste zuerst)."""
    messages = []
    while len(messages) < limit:
        batch = api(f'/channels/{channel_id}/messages', {'limit': min(100, limit - len(messages)), 'before': before, 'after': after})
        if not batch:
            break
        if after is not None:
            batch.reverse()  # Discord liefert auch mit `after` absteigend sortiert
            after = batch[-1]['id']
        else:
            before = batch[-1]['id']
        messages += batch
    return messages


def attachments_of(message):
    """Anhänge sowie Bilder aus Embeds als (Dateiname, URL, Größe)."""
    result = [(a['filename'], a['url'], a.get('size')) for a in message.get('attachments', [])]
    for embed in message.get('embeds', []):
        for key in ('image', 'thumbnail'):
            url = (embed.get(key) or {}).get('url')
            if url:
                result.append((os.path.basename(urllib.parse.urlparse(url).path) or key, url, None))
    return result


def cmd_guilds(_args):
    for guild in get_guilds():
        print(f"{guild['id']}  {guild['name']}")


def cmd_channels(args):
    guild = resolve_guild(args.guild)
    channels = get_channels(guild['id'])
    categories = {c['id']: c['name'] for c in channels if c['type'] == 4}
    for channel in sorted((c for c in channels if c['type'] != 4), key=lambda c: (categories.get(c.get('parent_id'), ''), c.get('position', 0))):
        kind = TEXT_CHANNEL_TYPES.get(channel['type'], str(channel['type']))
        print(f"{channel['id']}  {kind:<6} {categories.get(channel.get('parent_id'), '-')} / {channel['name']}")


def cmd_messages(args):
    messages = fetch_messages(resolve_channel(args.channel, args.guild), args.limit, args.before, args.after)
    if args.after is None:
        messages.reverse()  # chronologisch ausgeben
    if args.contains:
        messages = [m for m in messages if args.contains.lower() in m.get('content', '').lower()]
    if args.json:
        json.dump(messages, sys.stdout, ensure_ascii=False, indent=1)
        return
    for message in messages:
        author = message['author'].get('global_name') or message['author']['username']
        print(f"[{message['timestamp'][:19]}] {message['id']} {author}: {message.get('content', '')}")
        for filename, url, size in attachments_of(message):
            print(f"    Anhang: {filename}" + (f' ({size} Bytes)' if size else '') + f'  {url}')


def cmd_download(args):
    channel_id = resolve_channel(args.channel, args.guild)
    if args.message:
        messages = [api(f'/channels/{channel_id}/messages/{args.message}')]
    else:
        messages = fetch_messages(channel_id, args.limit, args.before, args.after)
    extensions = tuple('.' + e.strip().lower().lstrip('.') for e in args.ext.split(',')) if args.ext else None
    out_dir = args.out or os.path.join('downloads', channel_id)
    os.makedirs(out_dir, exist_ok=True)
    count = 0
    for message in messages:
        for filename, url, _size in attachments_of(message):
            if extensions and not filename.lower().endswith(extensions):
                continue
            if urllib.parse.urlparse(url).hostname not in CDN_HOSTS:
                print(f'Übersprungen (kein Discord-CDN): {url}')
                continue
            # Nachrichten-ID voranstellen: eindeutig und sortierbar; Dateiname von Sonderzeichen befreien
            target = os.path.join(out_dir, f"{message['id']}_{re.sub(r'[^A-Za-z0-9._-]', '_', filename)}")
            if not os.path.exists(target):
                request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
                with urllib.request.urlopen(request, timeout=60) as response, open(target, 'wb') as f:
                    while chunk := response.read(1 << 16):
                        f.write(chunk)
            count += 1
            print(target)
    print(f'{count} Datei(en) in {out_dir}')


def main():
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description='Lesender Discord-Zugriff über den Bot-Account.')
    sub = parser.add_subparsers(dest='command', required=True)

    sub.add_parser('guilds', help='Server des Bots auflisten').set_defaults(func=cmd_guilds)

    p = sub.add_parser('channels', help='Kanäle und aktive Threads eines Servers auflisten')
    p.add_argument('--guild', help='Server-ID oder -Name (nötig bei mehreren Servern)')
    p.set_defaults(func=cmd_channels)

    def add_selection(p):
        p.add_argument('channel', help='Kanal-ID oder -Name')
        p.add_argument('--guild', help='Server-ID oder -Name (für Kanalnamen bei mehreren Servern)')
        p.add_argument('--limit', type=int, default=50, help='Anzahl Nachrichten (Standard 50)')
        p.add_argument('--before', help='nur Nachrichten vor dieser Nachrichten-ID')
        p.add_argument('--after', help='nur Nachrichten nach dieser Nachrichten-ID')

    p = sub.add_parser('messages', help='Nachrichten eines Kanals lesen')
    add_selection(p)
    p.add_argument('--contains', help='nur Nachrichten, die diesen Text enthalten')
    p.add_argument('--json', action='store_true', help='rohe JSON-Ausgabe')
    p.set_defaults(func=cmd_messages)

    p = sub.add_parser('download', help='Anhänge aus Nachrichten herunterladen')
    add_selection(p)
    p.add_argument('--message', help='nur diese eine Nachrichten-ID')
    p.add_argument('--ext', help='Dateiendungen, z.B. png oder png,jpg')
    p.add_argument('--out', help='Zielordner (Standard: downloads/<Kanal-ID>)')
    p.set_defaults(func=cmd_download)

    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
