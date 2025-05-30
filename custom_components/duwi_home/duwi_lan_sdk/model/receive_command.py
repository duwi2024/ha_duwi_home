class ReceiveCommand:
    def __init__(self, sequence, data_json):
        self.sequence = sequence
        self.data_json = data_json

    def to_dict(self):
        return {
            "sequence": self.sequence,
            "data_json": self.data_json
        }
