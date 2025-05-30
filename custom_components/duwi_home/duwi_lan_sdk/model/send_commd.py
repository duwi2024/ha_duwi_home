class SendCommand:
    def __init__(self, host_sequence, count,command):
        self.host_sequence = host_sequence
        self.count = count
        self.command=command

    def to_dict(self):
        return {
            "host_sequence": self.host_sequence,
            "count": self.count,
            "command": self.command
        }
