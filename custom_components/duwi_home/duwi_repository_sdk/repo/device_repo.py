from typing import Type

from ...duwi_repository_sdk.model.device import Device
from ...duwi_repository_sdk.model.device_value import DeviceValue
from ...duwi_repository_sdk.repo.base_repo import Repository


class DeviceRepository:
    def __init__(self, base_repo: Repository):
        self.base_repo = base_repo

    def add_device(self, device: Device, device_values: list[DeviceValue] = None):
        session = self.base_repo.get_session()
        try:
            session.add(device)
            session.commit()
            if device_values:
                for device_value in device_values:
                    device_value.device_no = device.device_no
                    session.add(device_value)
            session.commit()
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()

    def remove_one_device(self, device_no: str = None):
        session = self.base_repo.get_session()
        try:
            device = session.query(Device).filter_by(device_no=device_no).first()
            if device:
                session.query(DeviceValue).filter_by(device_no=device_no).delete()
                session.delete(device)
                session.commit()
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()
