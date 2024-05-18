from strenum import StrEnum


class Emoji(StrEnum):
    PLAY = "▶️"
    PAUSE = "⏸️"
    STOP = "⏹️"
    VOLUME_UP = "🔊"
    VOLUME_DOWN = "🔉"
    BLACK_CIRCLE = "⚫"
    BLACK_SQUARE = "⬛"
    BLUE_CIRCLE ="🔵"
    BLUE_SQUARE = "🟦"
    BROWN_CIRCLE = "🟤"
    BROWN_SQUARE = "🟫"
    GREEN_CIRCLE = "🟢"
    GREEN_SQUARE = "🟩"
    ORANGE_CIRCLE = "🟠"
    ORANGE_SQUARE = "🟧"
    PURPLE_CIRCLE = "🟣"
    PURPLE_SQUARE = "🟪"
    RED_CIRCLE = "🔴"
    RED_SQUARE = "🟥"
    WHITE_CIRCLE = "⚪"
    WHITE_SQUARE = "⬜"
    YELLOW_CIRCLE = "🟡"
    YELLOW_SQUARE = "🟨"

    @classmethod
    def get_circles(cls):
        return [cls.BLACK_CIRCLE, cls.BLUE_CIRCLE, cls.BROWN_CIRCLE, cls.GREEN_CIRCLE, cls.ORANGE_CIRCLE, cls.PURPLE_CIRCLE, cls.RED_CIRCLE, cls.WHITE_CIRCLE, cls.YELLOW_CIRCLE]

    @classmethod
    def get_squares(cls):
        return [cls.BLACK_SQUARE, cls.BLUE_SQUARE, cls.BROWN_SQUARE, cls.GREEN_SQUARE, cls.ORANGE_SQUARE, cls.PURPLE_SQUARE, cls.RED_SQUARE, cls.WHITE_SQUARE, cls.YELLOW_SQUARE]
