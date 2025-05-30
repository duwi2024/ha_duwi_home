from xmlrpc.client import Boolean

from sqlalchemy import Column, String, Integer, SmallInteger

from .base import Base


class House(Base):
    __tablename__ = "house"

    id = Column(Integer, primary_key=True, autoincrement=True)
    house_no = Column(String(50))
    house_name = Column(String(50))
    lan_secret_key = Column(String(50))
