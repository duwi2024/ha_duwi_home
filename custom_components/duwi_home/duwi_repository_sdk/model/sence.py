from xmlrpc.client import Boolean

from sqlalchemy import Column, String, Integer, SmallInteger, JSON, inspect

from .base import Base


class Scene(Base):
    __tablename__ = "scene"

    id = Column(Integer, primary_key=True, autoincrement=True)
    scene_no = Column(String(50))
    scene_name = Column(String(50))
    room_no = Column(String(50))
    floor_no = Column(String(50))
    house_no = Column(String(50))
    sync_host_sequences = Column(JSON())
    execute_way = Column(SmallInteger)

    def to_camel_case(self, snake_str):
        components = snake_str.split('_')
        return components[0] + ''.join(x.title() for x in components[1:])

    def to_dict(self):
        return {self.to_camel_case(c.key): getattr(self, c.key) for c in inspect(self).mapper.column_attrs}
