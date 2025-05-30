from sqlalchemy import Column, String, Integer, SmallInteger, JSON, inspect

from .base import Base


class DeviceValue(Base):
    __tablename__ = "device_value"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_no = Column(String(50))
    code = Column(String(50))
    value = Column(JSON())

    def to_dict(self):
        return {c.key: getattr(self, c.key) for c in inspect(self).mapper.column_attrs}
