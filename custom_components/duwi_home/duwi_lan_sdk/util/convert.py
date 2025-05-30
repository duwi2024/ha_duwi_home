# coding=utf-8
import binascii
import hashlib
import random

"""
string转MD5
"""


def calculate_md5(input_string):
    md5_hash = hashlib.md5()
    md5_hash.update(input_string.encode("utf-8"))
    return md5_hash.hexdigest()


"""
string转二进制
"""


def string_to_binary(input_string):
    binary_data = input_string.encode("utf-8")
    return binary_data


"""
二进制转十六进制
"""


def binary_to_hex(binary_data):
    hex_string = binascii.hexlify(binary_data).decode("utf-8")
    return hex_string


"""
十进制转十六进制
"""


def decimal_to_hex(decimal_number):
    hex_string = hex(decimal_number)
    return hex_string[2:]


"""
获取随机数
"""


def get_random(mix):
    random_integer = random.randint(1, mix)
    return random_integer


"""
十六进制转二进制
"""


def hex_to_binary(hex_string):
    binary_data = binascii.unhexlify(hex_string)
    return binary_data


def get_hex_by_binary(binary):
    if binary == "0000":
        return "0"
    elif binary == "0001":
        return "1"
    elif binary == "0010":
        return "2"
    elif binary == "0011":
        return "3"
    elif binary == "0100":
        return "4"
    elif binary == "0101":
        return "5"
    elif binary == "0110":
        return "6"
    elif binary == "0111":
        return "7"
    elif binary == "1000":
        return "8"
    elif binary == "1001":
        return "9"
    elif binary == "1010":
        return "A"
    elif binary == "1011":
        return "B"
    elif binary == "1100":
        return "C"
    elif binary == "1101":
        return "D"
    elif binary == "1110":
        return "E"
    elif binary == "1111":
        return "F"
    else:
        return ""


def get_binary_by_hex(hex_str):
    hex_dict = {
            "0": "0000", "1": "0001", "2": "0010", "3": "0011",
            "4": "0100", "5": "0101", "6": "0110", "7": "0111",
            "8": "1000", "9": "1001", "A": "1010", "B": "1011",
            "C": "1100", "D": "1101", "E": "1110", "F": "1111"
        }
    binary = ""
    for char in hex_str.upper():
        if char in hex_dict:
            binary += hex_dict[char]
    return binary
