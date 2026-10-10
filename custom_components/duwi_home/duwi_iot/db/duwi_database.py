"""Duwi Iot Database"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import aiosqlite

from ..const import DUWI_DATABASE_NAME

_LOGGER = logging.getLogger(__name__)


class DuwiDatabase:
    """Duwi Iot Database."""

    def __init__(self, storage_dir: str):
        """Initialize database.

        Args:
            storage_dir: Storage directory path.
        """
        self._db_path = Path(storage_dir) / DUWI_DATABASE_NAME
        Path(storage_dir).mkdir(parents=True, exist_ok=True)
        self._connection: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        """Create database connection and initialize tables."""
        async with self._lock:
            if self._connection is None:
                self._connection = await aiosqlite.connect(self._db_path)
                self._connection.row_factory = aiosqlite.Row
                await self._connection.execute("PRAGMA journal_mode=WAL")
                await self._create_tables()
                _LOGGER.info("Database connected: %s", self._db_path)

    async def close(self) -> None:
        """Close database connection."""
        async with self._lock:
            if self._connection:
                await self._connection.close()
                self._connection = None
                _LOGGER.info("Database connection closed")

    async def _create_tables(self) -> None:
        """Create all required tables."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        tables = [
            """CREATE TABLE IF NOT EXISTS house (
                house_no TEXT PRIMARY KEY,
                house_name TEXT NOT NULL,
                address TEXT,
                location TEXT,
                update_time TEXT DEFAULT CURRENT_TIMESTAMP
            )""",
            """CREATE TABLE IF NOT EXISTS floor (
                floor_no TEXT PRIMARY KEY,
                house_no TEXT NOT NULL,
                floor_name TEXT NOT NULL,
                update_time TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (house_no) REFERENCES house(house_no) ON DELETE CASCADE
            )""",
            """CREATE TABLE IF NOT EXISTS room (
                room_no TEXT PRIMARY KEY,
                house_no TEXT NOT NULL,
                floor_no TEXT NOT NULL,
                room_name TEXT NOT NULL,
                update_time TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (house_no) REFERENCES house(house_no) ON DELETE CASCADE,
                FOREIGN KEY (floor_no) REFERENCES floor(floor_no) ON DELETE CASCADE
            )""",
            """CREATE TABLE IF NOT EXISTS device (
                device_no TEXT PRIMARY KEY,
                device_name TEXT NOT NULL,
                house_no TEXT NOT NULL,
                room_no TEXT,
                terminal_sequence TEXT,
                terminal_name TEXT,
                route_num INTEGER,
                is_use INTEGER,
                is_online INTEGER,
                device_type_no TEXT,
                device_sub_type_no TEXT,
                value TEXT,
                update_time TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (house_no) REFERENCES house(house_no) ON DELETE CASCADE,
                FOREIGN KEY (room_no) REFERENCES room(room_no) ON DELETE SET NULL
            )""",
            """CREATE TABLE IF NOT EXISTS device_group (
                device_group_no TEXT PRIMARY KEY,
                device_group_name TEXT NOT NULL,
                house_no TEXT NOT NULL,
                room_no TEXT,
                execute_way INTEGER,
                value TEXT,
                device_group_type TEXT,
                sync_host_sequences TEXT,
                update_time TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (house_no) REFERENCES house(house_no) ON DELETE CASCADE,
                FOREIGN KEY (room_no) REFERENCES room(room_no) ON DELETE SET NULL
            )""",
            """CREATE TABLE IF NOT EXISTS scene (
                scene_no TEXT PRIMARY KEY,
                scene_name TEXT NOT NULL,
                house_no TEXT NOT NULL,
                room_no TEXT,
                is_manual_execute INTEGER,
                is_use INTEGER,
                execute_way INTEGER,
                update_time TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (house_no) REFERENCES house(house_no) ON DELETE CASCADE,
                FOREIGN KEY (room_no) REFERENCES room(room_no) ON DELETE SET NULL
            )""",
            """CREATE TABLE IF NOT EXISTS terminal (
                terminal_sequence TEXT PRIMARY KEY,
                terminal_name TEXT NOT NULL,
                house_no TEXT NOT NULL,
                short_code TEXT,
                product_model TEXT,
                seq INTEGER,
                is_gateway INTEGER,
                host_sequence TEXT,
                is_follow_online INTEGER,
                is_online INTEGER,
                mac TEXT,
                update_time TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (house_no) REFERENCES house(house_no) ON DELETE CASCADE
            )""",
        ]

        for sql in tables:
            await self._connection.execute(sql)

        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_floors_house_no ON floor(house_no)",
            "CREATE INDEX IF NOT EXISTS idx_rooms_house_no ON room(house_no)",
            "CREATE INDEX IF NOT EXISTS idx_rooms_floor_no ON room(floor_no)",
            "CREATE INDEX IF NOT EXISTS idx_devices_house_no ON device(house_no)",
            "CREATE INDEX IF NOT EXISTS idx_devices_room_no ON device(room_no)",
            "CREATE INDEX IF NOT EXISTS idx_device_groups_house_no ON device_group(house_no)",
            "CREATE INDEX IF NOT EXISTS idx_device_groups_room_no ON device_group(room_no)",
            "CREATE INDEX IF NOT EXISTS idx_scenes_house_no ON scene(house_no)",
            "CREATE INDEX IF NOT EXISTS idx_scenes_room_no ON scene(room_no)",
            "CREATE INDEX IF NOT EXISTS idx_terminals_house_no ON terminal(house_no)",
            "CREATE INDEX IF NOT EXISTS idx_terminals_host_sequence ON terminal(host_sequence)",
        ]

        for idx_sql in indexes:
            await self._connection.execute(idx_sql)

        await self._connection.commit()
        _LOGGER.info("Database tables created successfully")

    def _check_connection(self) -> None:
        """Check database connection is available."""
        if not self._connection:
            raise RuntimeError("Database not connected")

    async def _execute_query(
        self,
        sql: str,
        params: tuple | None = None,
        fetch_one: bool = False,
    ) -> dict[str, Any] | list[dict[str, Any]] | None:
        """Execute a SELECT query with lock."""
        self._check_connection()
        assert self._connection is not None
        try:
            async with self._lock, self._connection.execute(sql, params) as cursor:
                if fetch_one:
                    row = await cursor.fetchone()
                    return dict(row) if row else None
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception:
            _LOGGER.error("Query failed: %s", sql[:80], exc_info=True)
            return None if fetch_one else []

    async def _execute_delete(self, sql: str, params: tuple) -> int:
        """Execute a DELETE statement and return the number of affected rows."""
        self._check_connection()
        assert self._connection is not None
        try:
            async with self._lock:
                try:
                    async with self._connection.execute(sql, params) as cursor:
                        rowcount = cursor.rowcount
                    await self._connection.commit()
                    return rowcount
                except Exception:
                    await self._connection.rollback()
                    raise
        except Exception:
            _LOGGER.error("Delete failed: %s", sql[:80], exc_info=True)
            return 0

    @staticmethod
    def _parse_device_value(data: dict[str, Any]) -> dict[str, Any]:
        """Parse JSON value field in device data."""
        if data.get("value"):
            data["value"] = json.loads(data["value"])
        return data

    @staticmethod
    def _parse_group_value(data: dict[str, Any]) -> dict[str, Any]:
        """Parse JSON value and sync_host_sequences fields in device group data."""
        if data.get("value"):
            data["value"] = json.loads(data["value"])
        raw = data.get("sync_host_sequences")
        if raw is None:
            data["sync_host_sequences"] = []
        elif isinstance(raw, str):
            data["sync_host_sequences"] = json.loads(raw)
        return data

    # ==================== House CRUD ====================

    async def insert_house(self, house_data: dict[str, Any]) -> dict[str, Any] | None:
        """Insert or update house information."""
        self._check_connection()
        assert self._connection is not None
        try:
            async with self._lock:
                house_no = house_data.get("houseNo")
                await self._connection.execute("""
                    INSERT INTO house (house_no, house_name, address, location)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(house_no) DO UPDATE SET
                        house_name=excluded.house_name,
                        address=excluded.address,
                        location=excluded.location,
                        update_time=CURRENT_TIMESTAMP
                """, (
                    house_no,
                    house_data.get("houseName"),
                    house_data.get("address"),
                    house_data.get("location"),
                ))
                await self._connection.commit()
                async with self._connection.execute(
                    "SELECT * FROM house WHERE house_no = ?", (house_no,)
                ) as cursor:
                    row = await cursor.fetchone()
                    return dict(row) if row else None
        except Exception:
            _LOGGER.error("Failed to insert house: %s", house_data.get("houseNo"), exc_info=True)
            return None

    async def get_house(self, house_no: str) -> dict[str, Any] | None:
        """Get house by house number."""
        return await self._execute_query(
            "SELECT * FROM house WHERE house_no = ?", (house_no,), fetch_one=True
        )

    async def get_all_houses(self) -> list[dict[str, Any]]:
        """Get all houses."""
        return await self._execute_query("SELECT * FROM house")

    async def delete_house(self, house_no: str) -> bool:
        """Delete house and related data."""
        return await self._execute_delete(
            "DELETE FROM house WHERE house_no = ?", (house_no,)
        ) > 0

    async def delete_all_by_house_no(self, house_no: str) -> int:
        """Delete all data for a specified house, including house itself."""
        self._check_connection()
        assert self._connection is not None
        try:
            async with self._lock:
                total_deleted = 0
                await self._connection.execute("BEGIN")
                try:
                    for table in ("scene", "device_group", "device", "terminal", "room", "floor", "house"):
                        async with self._connection.execute(
                            f"DELETE FROM {table} WHERE house_no = ?", (house_no,)
                        ) as cursor:
                            total_deleted += cursor.rowcount
                    await self._connection.commit()
                except Exception:
                    await self._connection.rollback()
                    raise
                _LOGGER.info(
                    "Deleted %d rows for house: %s", total_deleted, house_no
                )
                return total_deleted
        except Exception:
            _LOGGER.error(
                "Failed to delete all data for house: %s", house_no, exc_info=True
            )
            return 0

    # ==================== Floor CRUD ====================

    async def insert_floor(self, floor_data: dict[str, Any]) -> dict[str, Any] | None:
        """Insert or update floor information."""
        self._check_connection()
        assert self._connection is not None
        try:
            async with self._lock:
                floor_no = floor_data.get("floorNo")
                await self._connection.execute("""
                    INSERT INTO floor (floor_no, house_no, floor_name)
                    VALUES (?, ?, ?)
                    ON CONFLICT(floor_no) DO UPDATE SET
                        house_no=excluded.house_no,
                        floor_name=excluded.floor_name,
                        update_time=CURRENT_TIMESTAMP
                """, (
                    floor_no,
                    floor_data.get("houseNo"),
                    floor_data.get("floorName"),
                ))
                await self._connection.commit()
                async with self._connection.execute(
                    "SELECT * FROM floor WHERE floor_no = ?", (floor_no,)
                ) as cursor:
                    row = await cursor.fetchone()
                    return dict(row) if row else None
        except Exception:
            _LOGGER.error("Failed to insert floor: %s", floor_data.get("floorNo"), exc_info=True)
            return None

    async def get_floor(self, floor_no: str) -> dict[str, Any] | None:
        """Get floor by floor number."""
        return await self._execute_query(
            "SELECT * FROM floor WHERE floor_no = ?", (floor_no,), fetch_one=True
        )

    async def get_floors_by_house(self, house_no: str) -> list[dict[str, Any]]:
        """Get all floors for a house."""
        return await self._execute_query(
            "SELECT * FROM floor WHERE house_no = ?", (house_no,)
        )

    async def delete_floor(self, floor_no: str) -> bool:
        """Delete floor."""
        return await self._execute_delete(
            "DELETE FROM floor WHERE floor_no = ?", (floor_no,)
        ) > 0

    # ==================== Room CRUD ====================

    async def insert_room(self, room_data: dict[str, Any]) -> dict[str, Any] | None:
        """Insert or update room information."""
        self._check_connection()
        assert self._connection is not None
        try:
            async with self._lock:
                room_no = room_data.get("roomNo")
                await self._connection.execute("""
                    INSERT INTO room (room_no, house_no, floor_no, room_name)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(room_no) DO UPDATE SET
                        house_no=excluded.house_no,
                        floor_no=excluded.floor_no,
                        room_name=excluded.room_name,
                        update_time=CURRENT_TIMESTAMP
                """, (
                    room_no,
                    room_data.get("houseNo"),
                    room_data.get("floorNo"),
                    room_data.get("roomName"),
                ))
                await self._connection.commit()
                async with self._connection.execute(
                    "SELECT * FROM room WHERE room_no = ?", (room_no,)
                ) as cursor:
                    row = await cursor.fetchone()
                    return dict(row) if row else None
        except Exception:
            _LOGGER.error("Failed to insert room: %s", room_data.get("roomNo"), exc_info=True)
            return None

    async def get_room(self, room_no: str) -> dict[str, Any] | None:
        """Get room by room number."""
        return await self._execute_query(
            "SELECT * FROM room WHERE room_no = ?", (room_no,), fetch_one=True
        )

    async def get_rooms_by_house(self, house_no: str) -> list[dict[str, Any]]:
        """Get all rooms for a house."""
        return await self._execute_query(
            "SELECT * FROM room WHERE house_no = ?", (house_no,)
        )

    async def get_rooms_by_floor(self, floor_no: str) -> list[dict[str, Any]]:
        """Get all rooms for a floor."""
        return await self._execute_query(
            "SELECT * FROM room WHERE floor_no = ?", (floor_no,)
        )

    async def delete_room(self, room_no: str) -> bool:
        """Delete room."""
        return await self._execute_delete(
            "DELETE FROM room WHERE room_no = ?", (room_no,)
        ) > 0

    # ==================== Device CRUD ====================

    async def insert_device(self, device_data: dict[str, Any]) -> dict[str, Any] | None:
        """Insert or update device information."""
        self._check_connection()
        assert self._connection is not None
        try:
            async with self._lock:
                device_no = device_data.get("deviceNo")
                value = json.dumps(device_data.get("value")) if device_data.get("value") else None
                await self._connection.execute("""
                    INSERT INTO device (
                        device_no, device_name, house_no, room_no, terminal_sequence,
                        terminal_name, route_num, is_use, is_online, device_type_no,
                        device_sub_type_no, value
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(device_no) DO UPDATE SET
                        device_name=excluded.device_name,
                        house_no=excluded.house_no,
                        room_no=excluded.room_no,
                        terminal_sequence=excluded.terminal_sequence,
                        terminal_name=excluded.terminal_name,
                        route_num=excluded.route_num,
                        is_use=excluded.is_use,
                        is_online=excluded.is_online,
                        device_type_no=excluded.device_type_no,
                        device_sub_type_no=excluded.device_sub_type_no,
                        value=excluded.value,
                        update_time=CURRENT_TIMESTAMP
                """, (
                    device_no,
                    device_data.get("deviceName"),
                    device_data.get("houseNo"),
                    device_data.get("roomNo"),
                    device_data.get("terminalSequence"),
                    device_data.get("terminalName"),
                    device_data.get("routeNum"),
                    device_data.get("isUse"),
                    1 if device_data.get("isOnline") else 0,
                    device_data.get("deviceTypeNo"),
                    device_data.get("deviceSubTypeNo"),
                    value,
                ))
                await self._connection.commit()
                async with self._connection.execute(
                    "SELECT * FROM device WHERE device_no = ?", (device_no,)
                ) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        result = dict(row)
                        self._parse_device_value(result)
                        return result
                    return None
        except Exception:
            _LOGGER.error("Failed to insert device: %s", device_data.get("deviceNo"), exc_info=True)
            return None

    async def get_device(self, device_no: str) -> dict[str, Any] | None:
        """Get device by device number."""
        result = await self._execute_query(
            "SELECT * FROM device WHERE device_no = ?", (device_no,), fetch_one=True
        )
        if result:
            self._parse_device_value(result)
        return result

    async def get_devices_by_house(self, house_no: str) -> list[dict[str, Any]]:
        """Get all devices for a house."""
        results = await self._execute_query(
            "SELECT * FROM device WHERE house_no = ?", (house_no,)
        )
        for data in results:
            self._parse_device_value(data)
        return results

    async def get_devices_by_room(self, room_no: str) -> list[dict[str, Any]]:
        """Get all devices for a room."""
        results = await self._execute_query(
            "SELECT * FROM device WHERE room_no = ?", (room_no,)
        )
        for data in results:
            self._parse_device_value(data)
        return results

    async def get_online_devices_by_house(self, house_no: str) -> list[dict[str, Any]]:
        """Get all online devices for a house."""
        results = await self._execute_query(
            "SELECT * FROM device WHERE house_no = ? AND is_online = 1", (house_no,)
        )
        for data in results:
            self._parse_device_value(data)
        return results

    async def delete_device(self, device_no: str) -> bool:
        """Delete device."""
        return await self._execute_delete(
            "DELETE FROM device WHERE device_no = ?", (device_no,)
        ) > 0

    async def update_device_status(
        self, device_no: str, is_online: int, value: dict[str, Any] | None
    ) -> None:
        """Update only the online status and value of a device.

        Unlike insert_device, this preserves all other DB fields
        (terminal_name, room_no, etc.) and only refreshes real-time state.
        """
        self._check_connection()
        assert self._connection is not None
        try:
            async with self._lock:
                value_json = json.dumps(value) if value else None
                await self._connection.execute(
                    "UPDATE device SET is_online = ?, value = ?, update_time = CURRENT_TIMESTAMP WHERE device_no = ?",
                    (is_online, value_json, device_no),
                )
                await self._connection.commit()
        except Exception:
            _LOGGER.error("Failed to update device status: %s", device_no, exc_info=True)

    async def update_device_value(
        self, device_no: str, properties: dict[str, Any]
    ) -> None:
        """Merge property updates into the device value JSON.

        Reads the current value, merges the new properties, and writes back
        atomically (within the DB lock).
        """
        self._check_connection()
        assert self._connection is not None
        try:
            async with self._lock:
                async with self._connection.execute(
                    "SELECT value FROM device WHERE device_no = ?", (device_no,)
                ) as cursor:
                    row = await cursor.fetchone()
                    if not row:
                        return
                    current_value = json.loads(row["value"]) if row["value"] else {}
                current_value.update(properties)
                await self._connection.execute(
                    "UPDATE device SET value = ?, update_time = CURRENT_TIMESTAMP WHERE device_no = ?",
                    (json.dumps(current_value), device_no),
                )
                await self._connection.commit()
        except Exception:
            _LOGGER.error("Failed to merge device value: %s", device_no, exc_info=True)

    async def update_terminal_online(
        self, terminal_sequence: str, is_online: int
    ) -> None:
        """Update terminal online status only."""
        self._check_connection()
        assert self._connection is not None
        try:
            async with self._lock:
                await self._connection.execute(
                    "UPDATE terminal SET is_online = ?, update_time = CURRENT_TIMESTAMP WHERE terminal_sequence = ?",
                    (is_online, terminal_sequence),
                )
                await self._connection.commit()
        except Exception:
            _LOGGER.error("Failed to update terminal online: %s", terminal_sequence, exc_info=True)

    async def update_device_group_value(
        self, device_group_no: str, properties: dict[str, Any]
    ) -> None:
        """Merge property updates into the device group value JSON."""
        self._check_connection()
        assert self._connection is not None
        try:
            async with self._lock:
                async with self._connection.execute(
                    "SELECT value FROM device_group WHERE device_group_no = ?", (device_group_no,)
                ) as cursor:
                    row = await cursor.fetchone()
                    if not row:
                        return
                    current_value = json.loads(row["value"]) if row["value"] else {}
                current_value.update(properties)
                await self._connection.execute(
                    "UPDATE device_group SET value = ?, update_time = CURRENT_TIMESTAMP WHERE device_group_no = ?",
                    (json.dumps(current_value), device_group_no),
                )
                await self._connection.commit()
        except Exception:
            _LOGGER.error("Failed to merge device group value: %s", device_group_no, exc_info=True)

    # ==================== Device Group CRUD ====================

    async def insert_device_group(self, group_data: dict[str, Any]) -> dict[str, Any] | None:
        """Insert or update device group information."""
        self._check_connection()
        assert self._connection is not None
        try:
            async with self._lock:
                device_group_no = group_data.get("deviceGroupNo")
                value = json.dumps(group_data.get("value")) if group_data.get("value") else None
                raw_sync = group_data.get("syncHostSequences")
                sync_host_sequences = json.dumps(raw_sync) if raw_sync else "[]"
                await self._connection.execute("""
                    INSERT INTO device_group (
                        device_group_no, device_group_name, house_no, room_no,
                        execute_way, value, device_group_type, sync_host_sequences
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(device_group_no) DO UPDATE SET
                        device_group_name=excluded.device_group_name,
                        house_no=excluded.house_no,
                        room_no=excluded.room_no,
                        execute_way=excluded.execute_way,
                        value=excluded.value,
                        device_group_type=excluded.device_group_type,
                        sync_host_sequences=excluded.sync_host_sequences,
                        update_time=CURRENT_TIMESTAMP
                """, (
                    device_group_no,
                    group_data.get("deviceGroupName"),
                    group_data.get("houseNo"),
                    group_data.get("roomNo"),
                    group_data.get("executeWay"),
                    value,
                    group_data.get("deviceGroupType"),
                    sync_host_sequences,
                ))
                await self._connection.commit()
                async with self._connection.execute(
                    "SELECT * FROM device_group WHERE device_group_no = ?", (device_group_no,)
                ) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        result = dict(row)
                        self._parse_group_value(result)
                        return result
                    return None
        except Exception:
            _LOGGER.error("Failed to insert device group: %s", group_data.get("deviceGroupNo"), exc_info=True)
            return None

    async def get_device_group(self, group_no: str) -> dict[str, Any] | None:
        """Get device group by group number."""
        result = await self._execute_query(
            "SELECT * FROM device_group WHERE device_group_no = ?", (group_no,), fetch_one=True
        )
        if result:
            self._parse_group_value(result)
        return result

    async def get_device_groups_by_house(self, house_no: str) -> list[dict[str, Any]]:
        """Get all device groups for a house."""
        results = await self._execute_query(
            "SELECT * FROM device_group WHERE house_no = ?", (house_no,)
        )
        for data in results:
            self._parse_group_value(data)
        return results

    async def get_device_groups_by_room(self, room_no: str) -> list[dict[str, Any]]:
        """Get all device groups for a room."""
        results = await self._execute_query(
            "SELECT * FROM device_group WHERE room_no = ?", (room_no,)
        )
        for data in results:
            self._parse_group_value(data)
        return results

    async def delete_device_group(self, group_no: str) -> bool:
        """Delete device group."""
        return await self._execute_delete(
            "DELETE FROM device_group WHERE device_group_no = ?", (group_no,)
        ) > 0

    # ==================== Scene CRUD ====================

    async def insert_scene(self, scene_data: dict[str, Any]) -> dict[str, Any] | None:
        """Insert or update scene information."""
        self._check_connection()
        assert self._connection is not None
        try:
            async with self._lock:
                scene_no = scene_data.get("sceneNo")
                await self._connection.execute("""
                    INSERT INTO scene (
                        scene_no, scene_name, house_no, room_no,
                        is_manual_execute, is_use, execute_way
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(scene_no) DO UPDATE SET
                        scene_name=excluded.scene_name,
                        house_no=excluded.house_no,
                        room_no=excluded.room_no,
                        is_manual_execute=excluded.is_manual_execute,
                        is_use=excluded.is_use,
                        execute_way=excluded.execute_way,
                        update_time=CURRENT_TIMESTAMP
                """, (
                    scene_no,
                    scene_data.get("sceneName"),
                    scene_data.get("houseNo"),
                    scene_data.get("roomNo"),
                    1 if scene_data.get("isManualExecute") else 0,
                    1 if scene_data.get("isUse") else 0,
                    scene_data.get("executeWay"),
                ))
                await self._connection.commit()
                async with self._connection.execute(
                    "SELECT * FROM scene WHERE scene_no = ?", (scene_no,)
                ) as cursor:
                    row = await cursor.fetchone()
                    return dict(row) if row else None
        except Exception:
            _LOGGER.error("Failed to insert scene: %s", scene_data.get("sceneNo"), exc_info=True)
            return None

    async def get_scene(self, scene_no: str) -> dict[str, Any] | None:
        """Get scene by scene number."""
        return await self._execute_query(
            "SELECT * FROM scene WHERE scene_no = ?", (scene_no,), fetch_one=True
        )

    async def get_scenes_by_house(self, house_no: str) -> list[dict[str, Any]]:
        """Get all scenes for a house."""
        return await self._execute_query(
            "SELECT * FROM scene WHERE house_no = ?", (house_no,)
        )

    async def get_scenes_by_room(self, room_no: str) -> list[dict[str, Any]]:
        """Get all scenes for a room."""
        return await self._execute_query(
            "SELECT * FROM scene WHERE room_no = ?", (room_no,)
        )

    async def get_manual_execute_scenes(self, house_no: str) -> list[dict[str, Any]]:
        """Get all manually executable scenes for a house."""
        return await self._execute_query(
            "SELECT * FROM scene WHERE house_no = ? AND is_manual_execute = 1", (house_no,)
        )

    async def delete_scene(self, scene_no: str) -> bool:
        """Delete scene."""
        return await self._execute_delete(
            "DELETE FROM scene WHERE scene_no = ?", (scene_no,)
        ) > 0

    # ==================== Terminal (Controller) CRUD ====================

    async def insert_terminal(self,house_no:str, terminal_data: dict[str, Any]) -> dict[str, Any] | None:
        """Insert or update terminal (controller) information."""
        self._check_connection()
        assert self._connection is not None
        try:
            async with self._lock:
                terminal_sequence = terminal_data.get("terminalSequence")
                await self._connection.execute("""
                    INSERT INTO terminal (
                        terminal_sequence, terminal_name, house_no, short_code,
                        product_model, seq, is_gateway, host_sequence,
                        is_follow_online, is_online, mac
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(terminal_sequence) DO UPDATE SET
                        terminal_name=excluded.terminal_name,
                        house_no=excluded.house_no,
                        short_code=excluded.short_code,
                        product_model=excluded.product_model,
                        seq=excluded.seq,
                        is_gateway=excluded.is_gateway,
                        host_sequence=excluded.host_sequence,
                        is_follow_online=excluded.is_follow_online,
                        is_online=excluded.is_online,
                        mac=excluded.mac,
                        update_time=CURRENT_TIMESTAMP
                """, (
                    terminal_sequence,
                    terminal_data.get("terminalName"),
                    house_no,
                    terminal_data.get("shortCode"),
                    terminal_data.get("productModel"),
                    terminal_data.get("seq"),
                    1 if terminal_data.get("isGateWay") else 0,
                    terminal_data.get("hostSequence"),
                    1 if terminal_data.get("isFollowOnline") else 0,
                    1 if terminal_data.get("isOnline") else 0,
                    terminal_data.get("mac"),
                ))
                await self._connection.commit()
                async with self._connection.execute(
                    "SELECT * FROM terminal WHERE terminal_sequence = ?", (terminal_sequence,)
                ) as cursor:
                    row = await cursor.fetchone()
                    return dict(row) if row else None
        except Exception:
            _LOGGER.error("Failed to insert terminal: %s", terminal_data.get("terminalSequence"), exc_info=True)
            return None

    async def get_terminal(self, terminal_sequence: str) -> dict[str, Any] | None:
        """Get terminal by terminal sequence number."""
        return await self._execute_query(
            "SELECT * FROM terminal WHERE terminal_sequence = ?", (terminal_sequence,), fetch_one=True
        )

    async def get_terminals_by_house(self, house_no: str) -> list[dict[str, Any]]:
        """Get all terminals for a house."""
        return await self._execute_query(
            "SELECT * FROM terminal WHERE house_no = ?", (house_no,)
        )

    async def get_terminals_by_host(self, host_sequence: str) -> list[dict[str, Any]]:
        """Get all terminals for a host."""
        return await self._execute_query(
            "SELECT * FROM terminal WHERE host_sequence = ?", (host_sequence,)
        )

    async def get_gateway_terminals_by_house(self, house_no: str) -> list[dict[str, Any]]:
        """Get all gateway terminals for a house."""
        return await self._execute_query(
            "SELECT * FROM terminal WHERE house_no = ? AND is_gateway = 1", (house_no,)
        )

    async def get_online_terminals_by_house(self, house_no: str) -> list[dict[str, Any]]:
        """Get all online terminals for a house."""
        return await self._execute_query(
            "SELECT * FROM terminal WHERE house_no = ? AND is_online = 1", (house_no,)
        )

    async def delete_terminal(self, terminal_sequence: str) -> bool:
        """Delete terminal."""
        return await self._execute_delete(
            "DELETE FROM terminal WHERE terminal_sequence = ?", (terminal_sequence,)
        ) > 0

    # ==================== Batch Operations ====================

    async def sync_house_data(
        self,
        house_no: str,
        house_data: dict[str, Any],
        floors: list[dict[str, Any]],
        rooms: list[dict[str, Any]],
        devices: list[dict[str, Any]],
        groups: list[dict[str, Any]],
        scenes: list[dict[str, Any]],
        terminals: list[dict[str, Any]] | None = None,
    ) -> bool:
        """Synchronize all data for a house."""
        self._check_connection()
        assert self._connection is not None
        try:
            async with self._lock:
                await self._connection.execute("BEGIN")
                try:
                    if house_data:
                        await self._connection.execute("""
                            INSERT INTO house (house_no, house_name, address, location)
                            VALUES (?, ?, ?, ?)
                            ON CONFLICT(house_no) DO UPDATE SET
                                house_name=excluded.house_name,
                                address=excluded.address,
                                location=excluded.location,
                                update_time=CURRENT_TIMESTAMP
                        """, (
                            house_data.get("houseNo"),
                            house_data.get("houseName"),
                            house_data.get("address"),
                            house_data.get("location"),
                        ))

                    await self._connection.execute(
                        "DELETE FROM scene WHERE house_no = ?", (house_no,)
                    )
                    if scenes:
                        await self._connection.executemany("""
                            INSERT INTO scene (
                                scene_no, scene_name, house_no, room_no,
                                is_manual_execute, is_use, execute_way
                            ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, [
                            (
                                s.get("sceneNo"),
                                s.get("sceneName"),
                                s.get("houseNo"),
                                s.get("roomNo"),
                                1 if s.get("isManualExecute") else 0,
                                1 if s.get("isUse") else 0,
                                s.get("executeWay"),
                            )
                            for s in scenes
                        ])

                    await self._connection.execute(
                        "DELETE FROM device_group WHERE house_no = ?", (house_no,)
                    )
                    if groups:
                        await self._connection.executemany("""
                            INSERT INTO device_group (
                                device_group_no, device_group_name, house_no, room_no,
                                execute_way, value, device_group_type, sync_host_sequences
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """, [
                            (
                                g.get("deviceGroupNo"),
                                g.get("deviceGroupName"),
                                g.get("houseNo"),
                                g.get("roomNo"),
                                g.get("executeWay"),
                                json.dumps(g.get("value")) if g.get("value") else None,
                                g.get("deviceGroupType"),
                                json.dumps(g.get("syncHostSequences")) if g.get("syncHostSequences") else None,
                            )
                            for g in groups
                        ])

                    await self._connection.execute(
                        "DELETE FROM device WHERE house_no = ?", (house_no,)
                    )
                    if devices:
                        await self._connection.executemany("""
                            INSERT INTO device (
                                device_no, device_name, house_no, room_no, terminal_sequence,
                                terminal_name, route_num, is_use, is_online, device_type_no,
                                device_sub_type_no, value
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, [
                            (
                                d.get("deviceNo"),
                                d.get("deviceName"),
                                d.get("houseNo"),
                                d.get("roomNo"),
                                d.get("terminalSequence"),
                                d.get("terminalName"),
                                d.get("routeNum"),
                                d.get("isUse"),
                                1 if d.get("isOnline") else 0,
                                d.get("deviceTypeNo"),
                                d.get("deviceSubTypeNo"),
                                json.dumps(d.get("value")) if d.get("value") else None,
                            )
                            for d in devices
                        ])

                    await self._connection.execute(
                        "DELETE FROM terminal WHERE house_no = ?", (house_no,)
                    )
                    if terminals:
                        await self._connection.executemany("""
                            INSERT INTO terminal (
                                terminal_sequence, terminal_name, house_no, short_code,
                                product_model, seq, is_gateway, host_sequence,
                                is_follow_online, is_online, mac
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, [
                            (
                                t.get("terminalSequence"),
                                t.get("terminalName"),
                                house_no,
                                t.get("shortCode"),
                                t.get("productModel"),
                                t.get("seq"),
                                1 if t.get("isGateWay") else 0,
                                t.get("hostSequence"),
                                1 if t.get("isFollowOnline") else 0,
                                1 if t.get("isOnline") else 0,
                                t.get("mac"),
                            )
                            for t in terminals
                        ])

                    await self._connection.execute(
                        "DELETE FROM room WHERE house_no = ?", (house_no,)
                    )
                    if rooms:
                        await self._connection.executemany(
                            "INSERT INTO room (room_no, house_no, floor_no, room_name) VALUES (?, ?, ?, ?)",
                            [
                                (r.get("roomNo"), r.get("houseNo"), r.get("floorNo"), r.get("roomName"))
                                for r in rooms
                            ],
                        )

                    await self._connection.execute(
                        "DELETE FROM floor WHERE house_no = ?", (house_no,)
                    )
                    if floors:
                        await self._connection.executemany(
                            "INSERT INTO floor (floor_no, house_no, floor_name) VALUES (?, ?, ?)",
                            [
                                (f.get("floorNo"), f.get("houseNo"), f.get("floorName"))
                                for f in floors
                            ],
                        )

                    await self._connection.commit()
                except Exception:
                    await self._connection.rollback()
                    raise

                _LOGGER.info("House data synced successfully: %s", house_no)
                return True

        except Exception:
            _LOGGER.error("Failed to sync house data: %s", house_no, exc_info=True)
            return False

    # ==================== Utility Methods ====================

    async def get_house_full_info(self, house_no: str) -> dict[str, Any] | None:
        """Get complete house information including all related data."""
        self._check_connection()
        assert self._connection is not None
        try:
            async with self._lock:
                async with self._connection.execute(
                    "SELECT * FROM house WHERE house_no = ?", (house_no,)
                ) as cursor:
                    row = await cursor.fetchone()
                    if not row:
                        return None
                    house = dict(row)

                async with self._connection.execute(
                    "SELECT * FROM floor WHERE house_no = ?", (house_no,)
                ) as cursor:
                    house["floors"] = [dict(r) for r in await cursor.fetchall()]

                async with self._connection.execute(
                    "SELECT * FROM room WHERE house_no = ?", (house_no,)
                ) as cursor:
                    house["rooms"] = [dict(r) for r in await cursor.fetchall()]

                async with self._connection.execute(
                    "SELECT * FROM device WHERE house_no = ?", (house_no,)
                ) as cursor:
                    house["devices"] = [
                        self._parse_device_value(dict(r)) for r in await cursor.fetchall()
                    ]

                async with self._connection.execute(
                    "SELECT * FROM device_group WHERE house_no = ?", (house_no,)
                ) as cursor:
                    house["device_groups"] = [
                        self._parse_group_value(dict(r)) for r in await cursor.fetchall()
                    ]

                async with self._connection.execute(
                    "SELECT * FROM scene WHERE house_no = ?", (house_no,)
                ) as cursor:
                    house["scenes"] = [dict(r) for r in await cursor.fetchall()]

                async with self._connection.execute(
                    "SELECT * FROM terminal WHERE house_no = ?", (house_no,)
                ) as cursor:
                    house["terminals"] = [dict(r) for r in await cursor.fetchall()]

                return house
        except Exception:
            _LOGGER.error("Failed to get house full info: %s", house_no, exc_info=True)
            return None
