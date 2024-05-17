import configparser
import os


class Config:
    def __init__(self):
        self.cp = configparser.ConfigParser()

    def __read(self):
        self.cp.read('config.ini')

    def get_language_list(self, key):
        self.__read()
        return [s.strip() for s in self.cp.get('Language', key).split(',')]

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
        path = self.cp.get('Settings', 'music_path')
        if not os.path.exists(path):
            path = os.getcwd() + os.path.sep + "music"
            self.cp.set('Settings', 'music_path', path)
        return path

    def get_welcome_channel(self):
        self.__read()
        return self.cp.get('Settings', 'welcome_channel')


config = Config()
