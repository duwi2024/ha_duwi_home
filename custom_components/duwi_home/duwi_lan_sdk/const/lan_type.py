def get_con():
    return "00"


def get_non():
    return "01"


def get_ack():
    return "10"


def get_rst():
    return "11"


cases = {"CON": get_con, "NON": get_non, "ACK": get_ack, "RST": get_rst}
