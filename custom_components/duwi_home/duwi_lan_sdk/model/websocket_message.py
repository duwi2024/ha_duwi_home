class WebsocketMessage:
    def __init__(self, namespace, code, msg):
        self.namespace = namespace
        self.code = code
        self.msg = msg

    def to_dict(self):
        return {
            "namespace": self.namespace,
            "result": {"code": self.code, "msg": self.msg}
        }
