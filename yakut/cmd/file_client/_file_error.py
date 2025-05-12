import enum

class FileError(enum.IntEnum):
    OK = 0
    UNKNWOWN_ERROR = 65535

    NOT_FOUND = 2
    IO_ERROR = 5
    ACCESS_DENIED = 13
    IS_DIRECTORY = 21
    INVALID_VALUE = 22
    FILE_TOO_LARGE = 27
    OUT_OF_SPACE = 28
    NOT_SUPPORTED = 38
