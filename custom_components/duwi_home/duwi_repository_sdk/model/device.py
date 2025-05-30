from xmlrpc.client import Boolean

from sqlalchemy import Column, String, Integer, SmallInteger, inspect, JSON

from .base import Base


class Device(Base):
    __tablename__ = "device"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_no = Column(String(50))
    device_name = Column(String(50))
    device_type = Column(String(50))
    terminal_sequence = Column(String(50))
    route_num = Column(Integer)
    device_type_no = Column(String(20))
    device_sub_type_no = Column(String(20))
    house_no = Column(String(50))
    floor_no = Column(String(50))
    room_no = Column(String(50))
    create_time = Column(String)
    seq = Column(Integer)
    is_follow_online = Column(SmallInteger)
    is_favorite = Column(SmallInteger)
    favorite_time = Column(String)
    device_group_type = Column(String(50))
    hosts = Column(JSON())
    is_group = Column(SmallInteger)

    def to_camel_case(self, snake_str):
        components = snake_str.split('_')
        return components[0] + ''.join(x.title() for x in components[1:])

    def to_dict(self):
        return {self.to_camel_case(c.key): getattr(self, c.key) for c in inspect(self).mapper.column_attrs}
