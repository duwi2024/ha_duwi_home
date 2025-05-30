def get_power():
    return "device.power"


def get_light():
    return "device.light"


def get_curtain():
    return "device.curtain"


def get_hvac():
    return "device.hvac"


def get_swithpanel():
    return "device.switch_panel"


def get_securitysensor():
    return "device.security_sensor"


def get_video():
    return "device.video"


def get_remote():
    return "device.remote"


def get_protocol():
    return "device.protocol"


def get_terminal_host():
    return "terminal.host"


message_type_cases = {
    "1": get_power,
    "3": get_light,
    "4": get_curtain,
    "5": get_hvac,
    "6": get_swithpanel,
    "7": get_securitysensor,
    "8": get_video,
    "9": get_remote,
    "10": get_protocol,
}
