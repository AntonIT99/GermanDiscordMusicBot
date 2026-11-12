import configparser
import os

CONFIG_FILE = 'config.ini'


class Config:
    """
    Zugriff auf config.ini. Die Datei wird nur neu eingelesen, wenn sie sich geändert hat
    (Änderungen wirken also weiterhin ohne Neustart), statt bei jedem einzelnen Zugriff.
    """

    def __init__(self):
        self.cp = configparser.ConfigParser()
        self._mtime = None
        self._cache = {}

    def __read(self):
        try:
            mtime = os.stat(CONFIG_FILE).st_mtime_ns
        except OSError:
            mtime = 0
        if mtime != self._mtime:
            cp = configparser.ConfigParser()
            cp.read(CONFIG_FILE, encoding='utf-8-sig')
            self.cp = cp
            self._mtime = mtime
            self._cache = {}

    def get_language_list(self, key):
        self.__read()
        cache_key = ('Language', key)
        if cache_key not in self._cache:
            self._cache[cache_key] = tuple(s.strip() for s in self.cp.get('Language', key).split(',') if s.strip())
        return self._cache[cache_key]

    def get_command_prefix(self):
        self.__read()
        return self.cp.get('Settings', 'command_prefix')

    def get_token(self):
        self.__read()
        return self.cp.get('Settings', 'token')

    def get_owner_id(self):
        self.__read()
        owner_id = self.cp.get('Settings', 'owner_id')
        return int(owner_id) if owner_id.isdigit() else None

    def get_music_path(self):
        self.__read()
        if 'music_path' not in self._cache:
            path = self.cp.get('Settings', 'music_path', fallback='')
            if not path or not os.path.isdir(path):
                path = os.path.join(os.getcwd(), "music")
                os.makedirs(path, exist_ok=True)
            self._cache['music_path'] = path
        return self._cache['music_path']

    def get_welcome_channel(self):
        self.__read()
        return self.cp.get('Settings', 'welcome_channel')


config = Config()
