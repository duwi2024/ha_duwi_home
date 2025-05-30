import base64
import hashlib
import hmac


def md5_encrypt(input_string: str) -> str:
    md5 = hashlib.md5()
    md5.update(input_string.encode('utf-8'))
    encrypted_string = md5.hexdigest()
    return encrypted_string


def sha256_base64(client_id: str, app_key: str, time: str, secret_key: str) -> str:
    message = f"{client_id}{app_key}{time}"
    hmac_result = hmac.new(secret_key.encode(), message.encode(), hashlib.sha256).digest()
    sign = base64.b64encode(hmac_result).decode()
    return sign
