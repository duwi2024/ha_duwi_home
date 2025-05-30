import json

import math

from ..const.const import DUWI_LAN_VERSION, BEGIN_COMMAND, END_COMMAND, _LOGGER, DEVICE_ID
from ..const.lan_type import cases
from ..util.ace import encrypt_AES, decrypt_AES, hex_to_binary
from ..util.convert import (
    get_random,
    decimal_to_hex,
    get_hex_by_binary,
    get_binary_by_hex,
)
from ..model.receive_command import ReceiveCommand


def get_send_heart(lan_type, device_id):
    ver = DUWI_LAN_VERSION
    t = cases.get(lan_type, lambda: "9999")()
    if t == "9999":
        return 19998, "指令处理错误"

    message_id = (
        decimal_to_hex(get_random(15))
        + decimal_to_hex(get_random(15))
        + decimal_to_hex(get_random(15))
        + decimal_to_hex(get_random(15))
    )

    vart = get_hex_by_binary(ver + t)

    plll = "0"

    json_str = BEGIN_COMMAND + vart + plll + message_id + device_id + END_COMMAND
    json_str = json_str.upper()
    operate_command = hex_to_binary(json_str)
    return operate_command


def get_send_command(lan_secretkey, terminal_data_up, lan_type, device_id):
    ver = DUWI_LAN_VERSION
    t = cases.get(lan_type, lambda: "9999")()
    if t == "9999":
        return 19998, "指令处理错误"

    # _LOGGER.debug("发送指令: %s", terminal_data_up)

    json_data = encrypt_AES(lan_secretkey, terminal_data_up)

    pay_load_len = math.ceil(json_data.__len__() / 2)
    pay_load_len_hex = decimal_to_hex(pay_load_len)

    if pay_load_len_hex.__len__() % 2 != 0:
        pay_load_len_hex = "0" + pay_load_len_hex

    message_id = (
        decimal_to_hex(get_random(15))
        + decimal_to_hex(get_random(15))
        + decimal_to_hex(get_random(15))
        + decimal_to_hex(get_random(15))
    )

    vart = get_hex_by_binary(ver + t)

    plll = decimal_to_hex(int(pay_load_len_hex.__len__() / 2))

    json_str = (
        BEGIN_COMMAND
        + vart
        + plll
        + message_id
        + device_id
        + pay_load_len_hex
        + json_data
        + END_COMMAND
    )
    json_str = json_str.upper()

    operate_command = hex_to_binary(json_str)
    return operate_command


def get_receive_command(commandstr, hosts_lan_secret_key):
    # 去除包头和包尾
    # 判断当前数据是否符合数据格式
    model = ReceiveCommand("", "")

    data_str = commandstr.upper()

    if len(data_str) < 4:
        # 数据格式错误
        return model

    header_str = data_str[:4]
    footer_str = data_str[-4:]

    if header_str != BEGIN_COMMAND or footer_str != END_COMMAND:
        # 数据格式错误
        return model

    middle_str = data_str[4:-4]

    # 根据 middleStr 截取前两位获取 Var T PLLL
    var_t_plll_str = middle_str[:2]
    var_t_plll = get_binary_by_hex(var_t_plll_str)

    # 版本编号 Var
    var_str = var_t_plll[:2]
    # 报文类型 T 00需要被确认的报文 01不需要被确认的报文 10应答报文 11复位报文
    t_str = var_t_plll[2:4]
    # 负载长度字节数 PLLL
    plll_str = var_t_plll[4:]
    intercept = 0

    # 报文序号 Message ID
    message_id_str = middle_str[2:6]
    # 设备序号 Device ID
    device_id_str = middle_str[6:18]

    model.sequence = device_id_str

    if device_id_str == DEVICE_ID:
        return model

    if device_id_str in hosts_lan_secret_key:
        lan_secret_key = hosts_lan_secret_key[device_id_str]
    else:
        return model

    if plll_str == "0001":
        # 取1位
        intercept = 1
    elif plll_str == "0010":
        # 取2位
        intercept = 2
    elif plll_str == "0011":
        # 取3位
        intercept = 3
    elif plll_str == "0100":
        # 取4位
        intercept = 4
    else:
        # 心跳包 回应包
        return model

    # 负载长度 PayloadLen
    # 根据 intercept 截取长度
    if intercept == 0:
        # 结束
        return model

    payload_len_str = middle_str[18 : 18 + intercept * 2]

    # 转成10进制，用来截取后续负载 Payload
    payload_intercept = int(payload_len_str, 16)

    # 增加数据保护
    new_middle_str = middle_str[18 + intercept * 2 :]
    if len(new_middle_str) != payload_intercept * 2:
        model.status = False
        return model

    # 负载 Payload
    payload_str = middle_str[
        18 + intercept * 2 : 18 + intercept * 2 + payload_intercept * 2
    ]

    pay_data = hex_to_binary(payload_str)
    json_data = decrypt_AES(lan_secret_key, pay_data)

    try:
        model.data_json = json_data.decode("utf-8")
    except json.JSONDecodeError as e:
        print("json解析失败:", e)
    return model
