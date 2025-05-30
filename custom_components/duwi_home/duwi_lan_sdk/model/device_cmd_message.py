class DeviceCmdMessage:
    def __init__(self, traceid, version, type, data):
        self.traceId = traceid
        self.version = version
        self.type = type
        self.data = data

    def to_dict(self):
        return {
            "traceId": self.traceId,
            "version": self.version,
            "type": self.type,
            "data": self.data,
        }
