"""
Queue Manager for GrowMate Pods.

Handles SQLite-based offline queue for sensor data only (V2).
No image queue — V2 uses live H.264 stream instead of still captures.

Data Queue - Offline Operation
- Decouple data collection from upload
- Store failed uploads for retry
- Automatic cleanup of old entries (>24 hours)
- FIFO processing
"""

import sqlite3
import asyncio
import logging
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from pathlib import Path


logger = logging.getLogger("growmate.queue")

QUEUE_SCHEMA_VERSION = 2


class QueueManager:

    def __init__(self, db_path: Path, max_sensor_entries: int = 6000):
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None
        self.max_sensor_entries = max_sensor_entries

        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def _get_connection(self) -> sqlite3.Connection:
        if self.conn is None:
            self.conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                timeout=10.0
            )

            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA foreign_keys=ON")
            self.conn.row_factory = sqlite3.Row

            logger.info(f"Database connection established: {self.db_path}")

        return self.conn

    def initialize(self) -> bool:
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sensor_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    device_id TEXT NOT NULL,
                    firmware_version TEXT NOT NULL,
                    sensor_data TEXT NOT NULL,
                    current_state TEXT NOT NULL,
                    retry_count INTEGER DEFAULT 0,
                    last_retry_at TIMESTAMP,
                    status TEXT DEFAULT 'pending'
                )
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_sensor_queue_status
                ON sensor_queue(status)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_sensor_queue_created_at
                ON sensor_queue(created_at)
            """)

            # Drop image_queue table if it still exists from V1
            cursor.execute("""
                DROP TABLE IF EXISTS image_queue
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS queue_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cursor.execute("""
                INSERT OR IGNORE INTO queue_metadata (key, value) VALUES
                    ('schema_version', ?),
                    ('total_sensor_uploads', '0'),
                    ('total_failures', '0'),
                    ('last_successful_upload', NULL)
            """, (str(QUEUE_SCHEMA_VERSION),))

            conn.commit()
            logger.info("Database schema initialized (V2: sensor-only queue)")
            return True

        except sqlite3.Error as e:
            logger.error(f"Failed to initialize database schema: {e}")
            return False

    async def async_initialize(self) -> bool:
        return await asyncio.to_thread(self.initialize)

    def enqueue_sensor_data(
        self,
        device_id: str,
        firmware_version: str,
        sensor_data: List[Dict],
        current_state: Dict
    ) -> bool:
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) as count FROM sensor_queue")
            count = cursor.fetchone()['count']

            if count >= self.max_sensor_entries:
                cursor.execute("""
                    DELETE FROM sensor_queue
                    WHERE id = (SELECT MIN(id) FROM sensor_queue)
                """)
                logger.warning(
                    f"Sensor queue at capacity ({count}/{self.max_sensor_entries}), "
                    f"dropped oldest entry"
                )

            sensor_data_json = json.dumps(sensor_data)
            current_state_json = json.dumps(current_state)

            cursor.execute("""
                INSERT INTO sensor_queue
                (device_id, firmware_version, sensor_data, current_state, status)
                VALUES (?, ?, ?, ?, 'pending')
            """, (device_id, firmware_version, sensor_data_json, current_state_json))

            conn.commit()

            logger.debug(f"Enqueued sensor data: {len(sensor_data)} sensors")
            return True

        except sqlite3.Error as e:
            logger.error(f"Failed to enqueue sensor data: {e}")
            return False

    async def async_enqueue_sensor_data(
        self,
        device_id: str,
        firmware_version: str,
        sensor_data: List[Dict],
        current_state: Dict
    ) -> bool:
        return await asyncio.to_thread(
            self.enqueue_sensor_data,
            device_id,
            firmware_version,
            sensor_data,
            current_state
        )

    def dequeue_next_sensor(self) -> Optional[Dict[str, Any]]:
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute("""
                SELECT id, device_id, firmware_version, sensor_data, current_state, retry_count
                FROM sensor_queue
                WHERE status = 'pending'
                ORDER BY created_at ASC
                LIMIT 1
            """)

            row = cursor.fetchone()
            if not row:
                return None

            cursor.execute("""
                UPDATE sensor_queue
                SET status = 'uploading', last_retry_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (row['id'],))

            conn.commit()

            return {
                'id': row['id'],
                'device_id': row['device_id'],
                'firmware_version': row['firmware_version'],
                'sensor_data': json.loads(row['sensor_data']),
                'current_state': json.loads(row['current_state']),
                'retry_count': row['retry_count']
            }

        except sqlite3.Error as e:
            logger.error(f"Failed to dequeue sensor data: {e}")
            return None

    async def async_dequeue_next_sensor(self) -> Optional[Dict[str, Any]]:
        return await asyncio.to_thread(self.dequeue_next_sensor)

    def mark_sensor_uploaded(self, item_id: int) -> bool:
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute("DELETE FROM sensor_queue WHERE id = ?", (item_id,))

            cursor.execute("""
                UPDATE queue_metadata
                SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT),
                    updated_at = CURRENT_TIMESTAMP
                WHERE key = 'total_sensor_uploads'
            """)

            cursor.execute("""
                UPDATE queue_metadata
                SET value = datetime('now'),
                    updated_at = CURRENT_TIMESTAMP
                WHERE key = 'last_successful_upload'
            """)

            conn.commit()
            logger.debug(f"Marked sensor data as uploaded: ID {item_id}")
            return True

        except sqlite3.Error as e:
            logger.error(f"Failed to mark sensor data as uploaded: {e}")
            return False

    async def async_mark_sensor_uploaded(self, item_id: int) -> bool:
        return await asyncio.to_thread(self.mark_sensor_uploaded, item_id)

    def mark_sensor_failed(self, item_id: int, max_retries: int = 5) -> bool:
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute("SELECT retry_count FROM sensor_queue WHERE id = ?", (item_id,))
            row = cursor.fetchone()

            if not row:
                return False

            retry_count = row['retry_count'] + 1

            if retry_count >= max_retries:
                cursor.execute("DELETE FROM sensor_queue WHERE id = ?", (item_id,))
                logger.warning(f"Sensor data removed after {retry_count} failed attempts: ID {item_id}")

                cursor.execute("""
                    UPDATE queue_metadata
                    SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE key = 'total_failures'
                """)
            else:
                cursor.execute("""
                    UPDATE sensor_queue
                    SET status = 'pending', retry_count = ?
                    WHERE id = ?
                """, (retry_count, item_id))
                logger.debug(f"Sensor data marked for retry ({retry_count}/{max_retries}): ID {item_id}")

            conn.commit()
            return True

        except sqlite3.Error as e:
            logger.error(f"Failed to mark sensor data as failed: {e}")
            return False

    async def async_mark_sensor_failed(self, item_id: int, max_retries: int = 5) -> bool:
        return await asyncio.to_thread(self.mark_sensor_failed, item_id, max_retries)

    def get_queue_stats(self) -> Dict[str, Any]:
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
                    SUM(CASE WHEN status = 'uploading' THEN 1 ELSE 0 END) as uploading,
                    MIN(created_at) as oldest_entry
                FROM sensor_queue
            """)
            sensor_stats = dict(cursor.fetchone())

            cursor.execute("SELECT key, value FROM queue_metadata")
            metadata = {row['key']: row['value'] for row in cursor.fetchall()}

            return {
                'sensor_queue': sensor_stats,
                'metadata': metadata
            }

        except sqlite3.Error as e:
            logger.error(f"Failed to get queue stats: {e}")
            return {}

    async def async_get_queue_stats(self) -> Dict[str, Any]:
        return await asyncio.to_thread(self.get_queue_stats)

    def cleanup_old_entries(self, max_age_hours: int = 24) -> int:
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cutoff = datetime.now() - timedelta(hours=max_age_hours)
            cutoff_str = cutoff.strftime('%Y-%m-%d %H:%M:%S')

            cursor.execute("""
                DELETE FROM sensor_queue
                WHERE created_at < ?
            """, (cutoff_str,))
            sensor_count = cursor.rowcount

            conn.commit()

            if sensor_count > 0:
                logger.info(f"Cleaned up old queue entries: {sensor_count} sensors")

            return sensor_count

        except sqlite3.Error as e:
            logger.error(f"Failed to cleanup old entries: {e}")
            return 0

    async def async_cleanup_old_entries(self, max_age_hours: int = 24) -> int:
        return await asyncio.to_thread(self.cleanup_old_entries, max_age_hours)

    def vacuum(self) -> bool:
        try:
            conn = self._get_connection()
            conn.execute("VACUUM")
            logger.info("Database vacuumed successfully")
            return True

        except sqlite3.Error as e:
            logger.error(f"Failed to vacuum database: {e}")
            return False

    async def async_vacuum(self) -> bool:
        return await asyncio.to_thread(self.vacuum)

    def close(self):
        if self.conn:
            self.conn.close()
            self.conn = None
            logger.info("Database connection closed")

    async def async_close(self):
        await asyncio.to_thread(self.close)
