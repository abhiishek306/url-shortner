ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
BASE = len(ALPHABET)


def encode_base62(value: int) -> str:
    if value < 0:
        raise ValueError("Base62 encoder only supports non-negative integers")
    if value == 0:
        return ALPHABET[0]

    encoded = []
    number = value
    while number > 0:
        number, remainder = divmod(number, BASE)
        encoded.append(ALPHABET[remainder])
    return "".join(reversed(encoded))


def decode_base62(token: str) -> int:
    value = 0
    for char in token:
        value = value * BASE + ALPHABET.index(char)
    return value
