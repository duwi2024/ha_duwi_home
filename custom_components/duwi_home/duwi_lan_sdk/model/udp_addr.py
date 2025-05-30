class UdpAddr:
    def __init__(self, addrstr, terminalsequence):
        self.addrstr = addrstr
        self.terminalsequence = terminalsequence

    def to_dict(self):
        return {
            "addrstr": self.addrstr,
            "terminalsequence": self.terminalsequence,
        }
