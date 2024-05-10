import configparser


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

    def get_music_path(self):
        self.__read()
        return self.cp.get('Settings', 'music_path')

    def get_welcome_channel(self):
        self.__read()
        return self.cp.get('Settings', 'welcome_channel')
