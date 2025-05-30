from xmlrpc.client import Boolean

from sqlalchemy import Column, String, Integer, SmallInteger

from .base import Base


class Room(Base):
    __tablename__ = "room"

    id = Column(Integer, primary_key=True, autoincrement=True)
    room_no = Column(String(50))
    room_name = Column(String(50))
