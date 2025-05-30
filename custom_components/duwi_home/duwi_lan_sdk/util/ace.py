# coding=utf-8
import binascii
import hashlib
from binascii import hexlify
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import padding

"""
加密
"""


def calculate_md5(input_string):
    md5_hash = hashlib.md5(input_string)
    return md5_hash.hexdigest()


"""
string转二进制
"""


def string_to_binary(input_string):
    binary_data = input_string.encode("utf-8")
    return binary_data


def hex_to_binary(hex_string):
    binary_data = binascii.unhexlify(hex_string)
    return binary_data


def encrypt_AES(key, data):
    backend = default_backend()

    iv = calculate_md5(hex_to_binary(key))  # 生成向量

    cipher = Cipher(algorithms.AES(hex_to_binary(key)), modes.CBC(hex_to_binary(iv)), backend=backend)
    encryptor = cipher.encryptor()

    padder = padding.PKCS7(128).padder()
    padded_data = padder.update(string_to_binary(data)) + padder.finalize()

    ct = encryptor.update(padded_data) + encryptor.finalize()

    return hexlify(ct).decode('utf-8')


"""
解密
"""


def decrypt_AES(key, data):
    backend = default_backend()
    iv = calculate_md5(hex_to_binary(key))
    ct = data

    cipher = Cipher(algorithms.AES(hex_to_binary(key)), modes.CBC(hex_to_binary(iv)), backend=backend)
    decryptor = cipher.decryptor()

    padded_data = decryptor.update(ct) + decryptor.finalize()

    unpadder = padding.PKCS7(128).unpadder()
    data = unpadder.update(padded_data) + unpadder.finalize()

    return data
