import sqlalchemy

from ...duwi_repository_sdk.model.device_value import DeviceValue
from ...duwi_repository_sdk.repo.base_repo import Repository
from ..const.const import _LOGGER


class DeviceValueRepository:
    def __init__(self, base_repo: Repository):
        self.base_repo = base_repo

    def update_device_values(self, device_values: list[DeviceValue]):
        session = self.base_repo.get_session()
        try:
            for device_value in device_values:
                # 查找匹配的记录
                existing_device_value = session.query(DeviceValue).filter_by(device_no=device_value.device_no,
                                                                             code=device_value.code).first()
                if existing_device_value:
                    # 更新匹配记录的字段
                    existing_device_value.value = device_value.value
            session.commit()
        except sqlalchemy.exc.OperationalError as e:
            session.rollback()
            _LOGGER.error(f"OperationalError occurred: {e}")
            if "readonly database" in str(e):
                _LOGGER.error("Attempted to write to a readonly database.")
                # raise e
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()
