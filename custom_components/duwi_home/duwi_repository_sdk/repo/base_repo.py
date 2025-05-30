import os
import sqlite3
import time
from sqlite3 import OperationalError
from typing import Type, Any, Union, TypeVar, Optional

from sqlalchemy import create_engine, MetaData, Table, text
from sqlalchemy.future import engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session

from ...duwi_repository_sdk.model.base import Base
from ...duwi_repository_sdk.const.const import _LOGGER

T = TypeVar('T', bound=Base)


class Repository:
    def __init__(self, entry_id: str):
        # 获取组件所在的目录
        current_path = os.path.dirname(os.path.abspath(__file__))
        os.makedirs(current_path + "/database", exist_ok=True)
        # 创建sqlite连接引擎
        self._entry_id = entry_id
        self.db_path = current_path + "/database/duwi-" + entry_id + ".db"
        self.Session = None
        self.engine = None
        _LOGGER.info("Repository init success")

    def init_db(self):
        self.engine = create_engine("sqlite:///" + self.db_path, echo=False)
        self.Session = sessionmaker(bind=self.engine)
        # 创建所有表
        Base.metadata.create_all(self.engine)

    def get_session(self):
        if not self.Session:
            return
        return self.Session()

    def clear_all_table(self):
        # 确保没有其他任务在进行写操作
        self._ensure_no_active_sessions()

        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
                _LOGGER.info("Database file deleted successfully")
            except Exception as e:
                _LOGGER.error(f"Failed to delete database file: {e}")
        else:
            _LOGGER.error("Database file does not exist")

    def _ensure_no_active_sessions(self):
        session = self.get_session()
        if session is None:
            # _LOGGER.debug("No active sessions, safe to delete the database file.")
            return
        try:
            # 尝试获取一个数据库连接
            session.execute(text("SELECT 1"))
            _LOGGER.info("No active sessions, safe to delete the database file.")
        except OperationalError:
            _LOGGER.warning("There are active sessions, waiting...")
            time.sleep(1)  # 等待一秒后再检查
            self._ensure_no_active_sessions()
        finally:
            if session:
                session.close()

    def get_one_entity(self, entity_type: Type[T], id: str) -> Optional[T]:
        session: Session = self.get_session()
        try:
            entity = session.query(entity_type).filter_by(id=id).first()
            return entity
        finally:
            session.close()

    def add_entity(self, entity: T):
        session = self.get_session()
        try:
            session.add(entity)
            session.commit()
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()

    def list_entities(self, entity_type: Type[T]) -> list[T]:
        session: Session = self.get_session()
        try:
            entities = session.query(entity_type).all()
            return entities
        finally:
            session.close()

    def update_entity(self, entity: T):
        session = self.get_session()
        try:
            session.merge(entity)
            session.commit()
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()

    def remove_entity(self, entity: Type[T], id: str = None):
        session = self.get_session()
        try:
            entity = self.get_one_entity(entity, id)
            session.delete(entity)
            session.commit()
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()

    def add_entities(self, entities: list[T]):
        session = self.get_session()
        try:
            session.add_all(entities)
            session.commit()
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()
