from xmlrpc.client import Boolean

from sqlalchemy import Column, String, Integer, SmallInteger

from .base import Base


class Floor(Base):
    __tablename__ = "floor"

    id = Column(Integer, primary_key=True, autoincrement=True)
    floor_no = Column(String(50))
    floor_name = Column(String(50))


