from xmlrpc.client import Boolean

from sqlalchemy import Column, String, Integer, SmallInteger

from .base import Base


class Terminal(Base):
    __tablename__ = "terminal"

    id = Column(Integer, primary_key=True, autoincrement=True)
    terminal_sequence = Column(String(50))
    host_sequence = Column(String(50))
    product_model = Column(String(50))
