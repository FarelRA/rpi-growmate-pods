"""
Queue Manager for GrowMate Pods.

Handles SQLite-based offline queue for sensor data and camera images.
Provides 1-day capacity for offline operation (~147MB storage).

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


# Database schema version
QUEUE_SCHEMA_VERSION = 1


class QueueManager:
    """Manages SQLite-based offline queue for sensor data and images."""
    
    def __init__(self, db_path: Path, max_sensor_entries: int = 6000, max_image_entries: int = 100):
        """
        Initialize queue manager.
        
        Args:
            db_path: Path to SQLite database file
            max_sensor_entries: Maximum sensor queue entries (default: 6000, ~1 day at 15s intervals)
            max_image_entries: Maximum image queue entries (default: 100, ~1 day at 15m intervals)
        """
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None
        self.max_sensor_entries = max_sensor_entries
        self.max_image_entries = max_image_entries
        
        # Ensure database directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
    
    def _get_connection(self) -> sqlite3.Connection:
        """
        Get database connection (creates if needed).
        
        Returns:
            SQLite connection
        """
        if self.conn is None:
            self.conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,  # Allow use from different threads
                timeout=10.0  # Wait up to 10s for locks
            )
            
            # Enable WAL mode for better concurrency (RPI optimization)
            self.conn.execute("PRAGMA journal_mode=WAL")
            
            # Enable foreign keys
            self.conn.execute("PRAGMA foreign_keys=ON")
            
            # Row factory for dict-like access
            self.conn.row_factory = sqlite3.Row
            
            logger.info(f"Database connection established: {self.db_path}")
        
        return self.conn
    
    def initialize(self) -> bool:
        """
        Initialize database schema.
        
        Creates tables if they don't exist.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Create sensor_queue table
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
            
            # Create indexes for sensor_queue
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_sensor_queue_status 
                ON sensor_queue(status)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_sensor_queue_created_at 
                ON sensor_queue(created_at)
            """)
            
            # Create image_queue table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS image_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    device_id TEXT NOT NULL,
                    image_data BLOB NOT NULL,
                    image_size INTEGER NOT NULL,
                    metadata TEXT,
                    retry_count INTEGER DEFAULT 0,
                    last_retry_at TIMESTAMP,
                    status TEXT DEFAULT 'pending'
                )
            """)
            
            # Create indexes for image_queue
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_image_queue_status 
                ON image_queue(status)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_image_queue_created_at 
                ON image_queue(created_at)
            """)
            
            # Create queue_metadata table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS queue_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Initialize metadata (if not exists)
            cursor.execute("""
                INSERT OR IGNORE INTO queue_metadata (key, value) VALUES 
                    ('schema_version', ?),
                    ('total_sensor_uploads', '0'),
                    ('total_image_uploads', '0'),
                    ('total_failures', '0'),
                    ('last_successful_upload', NULL)
            """, (str(QUEUE_SCHEMA_VERSION),))
            
            conn.commit()
            logger.info("Database schema initialized successfully")
            return True
            
        except sqlite3.Error as e:
            logger.error(f"Failed to initialize database schema: {e}")
            return False
    
    async def async_initialize(self) -> bool:
        """Async wrapper for initialize()."""
        return await asyncio.to_thread(self.initialize)
    
    def enqueue_sensor_data(
        self,
        device_id: str,
        firmware_version: str,
        sensor_data: List[Dict],
        current_state: Dict
    ) -> bool:
        """
        Add sensor data to queue.
        
        Enforces capacity limit by dropping oldest entries when at capacity.
        
        Args:
            device_id: Device identifier
            firmware_version: Firmware version
            sensor_data: List of sensor readings
            current_state: Current actuator state
            
        Returns:
            True if successful, False otherwise
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Enforce capacity limit (prevent unbounded growth)
            cursor.execute("SELECT COUNT(*) as count FROM sensor_queue")
            count = cursor.fetchone()['count']
            
            if count >= self.max_sensor_entries:
                # Drop oldest entry to make room
                cursor.execute("""
                    DELETE FROM sensor_queue 
                    WHERE id = (SELECT MIN(id) FROM sensor_queue)
                """)
                logger.warning(
                    f"Sensor queue at capacity ({count}/{self.max_sensor_entries}), "
                    f"dropped oldest entry"
                )
            
            # Serialize data to JSON
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
        """Async wrapper for enqueue_sensor_data()."""
        return await asyncio.to_thread(
            self.enqueue_sensor_data,
            device_id,
            firmware_version,
            sensor_data,
            current_state
        )
    
    def enqueue_image(
        self,
        device_id: str,
        image_data: bytes,
        metadata: Optional[Dict] = None
    ) -> bool:
        """
        Add image to queue.
        
        Enforces capacity limit by dropping oldest entries when at capacity.
        
        Args:
            device_id: Device identifier
            image_data: JPEG image bytes
            metadata: Optional metadata (EXIF, sensor readings, etc.)
            
        Returns:
            True if successful, False otherwise
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Enforce capacity limit (prevent unbounded growth)
            cursor.execute("SELECT COUNT(*) as count FROM image_queue")
            count = cursor.fetchone()['count']
            
            if count >= self.max_image_entries:
                # Drop oldest entry to make room
                cursor.execute("""
                    DELETE FROM image_queue 
                    WHERE id = (SELECT MIN(id) FROM image_queue)
                """)
                logger.warning(
                    f"Image queue at capacity ({count}/{self.max_image_entries}), "
                    f"dropped oldest entry"
                )
            
            # Serialize metadata to JSON
            metadata_json = json.dumps(metadata) if metadata else None
            image_size = len(image_data)
            
            cursor.execute("""
                INSERT INTO image_queue 
                (device_id, image_data, image_size, metadata, status)
                VALUES (?, ?, ?, ?, 'pending')
            """, (device_id, image_data, image_size, metadata_json))
            
            conn.commit()
            
            logger.debug(f"Enqueued image: {image_size} bytes")
            return True
            
        except sqlite3.Error as e:
            logger.error(f"Failed to enqueue image: {e}")
            return False
    
    async def async_enqueue_image(
        self,
        device_id: str,
        image_data: bytes,
        metadata: Optional[Dict] = None
    ) -> bool:
        """Async wrapper for enqueue_image()."""
        return await asyncio.to_thread(
            self.enqueue_image,
            device_id,
            image_data,
            metadata
        )
    
    def dequeue_next_sensor(self) -> Optional[Dict[str, Any]]:
        """
        Get next sensor data item from queue (FIFO).
        
        Returns oldest pending item and marks it as 'uploading'.
        
        Returns:
            Dictionary with queue item data, or None if queue is empty
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Get oldest pending item
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
            
            # Mark as uploading
            cursor.execute("""
                UPDATE sensor_queue
                SET status = 'uploading', last_retry_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (row['id'],))
            
            conn.commit()
            
            # Parse JSON data
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
        """Async wrapper for dequeue_next_sensor()."""
        return await asyncio.to_thread(self.dequeue_next_sensor)
    
    def dequeue_next_image(self) -> Optional[Dict[str, Any]]:
        """
        Get next image item from queue (FIFO).
        
        Returns oldest pending item and marks it as 'uploading'.
        
        Returns:
            Dictionary with queue item data, or None if queue is empty
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Get oldest pending item
            cursor.execute("""
                SELECT id, device_id, image_data, image_size, metadata, retry_count
                FROM image_queue
                WHERE status = 'pending'
                ORDER BY created_at ASC
                LIMIT 1
            """)
            
            row = cursor.fetchone()
            if not row:
                return None
            
            # Mark as uploading
            cursor.execute("""
                UPDATE image_queue
                SET status = 'uploading', last_retry_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (row['id'],))
            
            conn.commit()
            
            # Parse metadata
            metadata = json.loads(row['metadata']) if row['metadata'] else None
            
            return {
                'id': row['id'],
                'device_id': row['device_id'],
                'image_data': row['image_data'],
                'image_size': row['image_size'],
                'metadata': metadata,
                'retry_count': row['retry_count']
            }
            
        except sqlite3.Error as e:
            logger.error(f"Failed to dequeue image: {e}")
            return None
    
    async def async_dequeue_next_image(self) -> Optional[Dict[str, Any]]:
        """Async wrapper for dequeue_next_image()."""
        return await asyncio.to_thread(self.dequeue_next_image)
    
    def mark_sensor_uploaded(self, item_id: int) -> bool:
        """
        Mark sensor data as successfully uploaded (removes from queue).
        
        Args:
            item_id: Queue item ID
            
        Returns:
            True if successful, False otherwise
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Delete from queue
            cursor.execute("DELETE FROM sensor_queue WHERE id = ?", (item_id,))
            
            # Update statistics
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
        """Async wrapper for mark_sensor_uploaded()."""
        return await asyncio.to_thread(self.mark_sensor_uploaded, item_id)
    
    def mark_image_uploaded(self, item_id: int) -> bool:
        """
        Mark image as successfully uploaded (removes from queue).
        
        Args:
            item_id: Queue item ID
            
        Returns:
            True if successful, False otherwise
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Delete from queue
            cursor.execute("DELETE FROM image_queue WHERE id = ?", (item_id,))
            
            # Update statistics
            cursor.execute("""
                UPDATE queue_metadata 
                SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT),
                    updated_at = CURRENT_TIMESTAMP
                WHERE key = 'total_image_uploads'
            """)
            
            cursor.execute("""
                UPDATE queue_metadata 
                SET value = datetime('now'),
                    updated_at = CURRENT_TIMESTAMP
                WHERE key = 'last_successful_upload'
            """)
            
            conn.commit()
            logger.debug(f"Marked image as uploaded: ID {item_id}")
            return True
            
        except sqlite3.Error as e:
            logger.error(f"Failed to mark image as uploaded: {e}")
            return False
    
    async def async_mark_image_uploaded(self, item_id: int) -> bool:
        """Async wrapper for mark_image_uploaded()."""
        return await asyncio.to_thread(self.mark_image_uploaded, item_id)
    
    def mark_sensor_failed(self, item_id: int, max_retries: int = 5) -> bool:
        """
        Mark sensor data upload as failed.
        
        Increments retry count. If max retries exceeded, removes from queue.
        Otherwise, marks as 'pending' for retry.
        
        Args:
            item_id: Queue item ID
            max_retries: Maximum retry attempts before giving up
            
        Returns:
            True if successful, False otherwise
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Get current retry count
            cursor.execute("SELECT retry_count FROM sensor_queue WHERE id = ?", (item_id,))
            row = cursor.fetchone()
            
            if not row:
                return False
            
            retry_count = row['retry_count'] + 1
            
            if retry_count >= max_retries:
                # Max retries exceeded, remove from queue
                cursor.execute("DELETE FROM sensor_queue WHERE id = ?", (item_id,))
                logger.warning(f"Sensor data removed after {retry_count} failed attempts: ID {item_id}")
                
                # Update failure statistics
                cursor.execute("""
                    UPDATE queue_metadata 
                    SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE key = 'total_failures'
                """)
            else:
                # Mark as pending for retry
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
        """Async wrapper for mark_sensor_failed()."""
        return await asyncio.to_thread(self.mark_sensor_failed, item_id, max_retries)
    
    def mark_image_failed(self, item_id: int, max_retries: int = 5) -> bool:
        """
        Mark image upload as failed.
        
        Increments retry count. If max retries exceeded, removes from queue.
        Otherwise, marks as 'pending' for retry.
        
        Args:
            item_id: Queue item ID
            max_retries: Maximum retry attempts before giving up
            
        Returns:
            True if successful, False otherwise
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Get current retry count
            cursor.execute("SELECT retry_count FROM image_queue WHERE id = ?", (item_id,))
            row = cursor.fetchone()
            
            if not row:
                return False
            
            retry_count = row['retry_count'] + 1
            
            if retry_count >= max_retries:
                # Max retries exceeded, remove from queue
                cursor.execute("DELETE FROM image_queue WHERE id = ?", (item_id,))
                logger.warning(f"Image removed after {retry_count} failed attempts: ID {item_id}")
                
                # Update failure statistics
                cursor.execute("""
                    UPDATE queue_metadata 
                    SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE key = 'total_failures'
                """)
            else:
                # Mark as pending for retry
                cursor.execute("""
                    UPDATE image_queue
                    SET status = 'pending', retry_count = ?
                    WHERE id = ?
                """, (retry_count, item_id))
                logger.debug(f"Image marked for retry ({retry_count}/{max_retries}): ID {item_id}")
            
            conn.commit()
            return True
            
        except sqlite3.Error as e:
            logger.error(f"Failed to mark image as failed: {e}")
            return False
    
    async def async_mark_image_failed(self, item_id: int, max_retries: int = 5) -> bool:
        """Async wrapper for mark_image_failed()."""
        return await asyncio.to_thread(self.mark_image_failed, item_id, max_retries)
    
    def get_queue_stats(self) -> Dict[str, Any]:
        """
        Get queue statistics.
        
        Returns:
            Dictionary with queue statistics
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Get sensor queue stats
            cursor.execute("""
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
                    SUM(CASE WHEN status = 'uploading' THEN 1 ELSE 0 END) as uploading,
                    MIN(created_at) as oldest_entry
                FROM sensor_queue
            """)
            sensor_stats = dict(cursor.fetchone())
            
            # Get image queue stats
            cursor.execute("""
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
                    SUM(CASE WHEN status = 'uploading' THEN 1 ELSE 0 END) as uploading,
                    SUM(image_size) as total_size,
                    MIN(created_at) as oldest_entry
                FROM image_queue
            """)
            image_stats = dict(cursor.fetchone())
            
            # Get metadata
            cursor.execute("SELECT key, value FROM queue_metadata")
            metadata = {row['key']: row['value'] for row in cursor.fetchall()}
            
            return {
                'sensor_queue': sensor_stats,
                'image_queue': image_stats,
                'metadata': metadata
            }
            
        except sqlite3.Error as e:
            logger.error(f"Failed to get queue stats: {e}")
            return {}
    
    async def async_get_queue_stats(self) -> Dict[str, Any]:
        """Async wrapper for get_queue_stats()."""
        return await asyncio.to_thread(self.get_queue_stats)
    
    def cleanup_old_entries(self, max_age_hours: int = 24) -> Tuple[int, int]:
        """
        Clean up old entries from queue.
        
        Removes entries older than max_age_hours.
        
        Args:
            max_age_hours: Maximum age in hours (default: 24)
            
        Returns:
            Tuple of (sensor_count, image_count) deleted
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Calculate cutoff time
            cutoff = datetime.now() - timedelta(hours=max_age_hours)
            cutoff_str = cutoff.strftime('%Y-%m-%d %H:%M:%S')
            
            # Delete old sensor data
            cursor.execute("""
                DELETE FROM sensor_queue
                WHERE created_at < ?
            """, (cutoff_str,))
            sensor_count = cursor.rowcount
            
            # Delete old images
            cursor.execute("""
                DELETE FROM image_queue
                WHERE created_at < ?
            """, (cutoff_str,))
            image_count = cursor.rowcount
            
            conn.commit()
            
            if sensor_count > 0 or image_count > 0:
                logger.info(
                    f"Cleaned up old queue entries: "
                    f"{sensor_count} sensors, {image_count} images"
                )
            
            return (sensor_count, image_count)
            
        except sqlite3.Error as e:
            logger.error(f"Failed to cleanup old entries: {e}")
            return (0, 0)
    
    async def async_cleanup_old_entries(self, max_age_hours: int = 24) -> Tuple[int, int]:
        """Async wrapper for cleanup_old_entries()."""
        return await asyncio.to_thread(self.cleanup_old_entries, max_age_hours)
    
    def vacuum(self) -> bool:
        """
        Vacuum database to reclaim space.
        
        Should be run periodically (e.g., weekly) to optimize database.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            conn = self._get_connection()
            conn.execute("VACUUM")
            logger.info("Database vacuumed successfully")
            return True
            
        except sqlite3.Error as e:
            logger.error(f"Failed to vacuum database: {e}")
            return False
    
    async def async_vacuum(self) -> bool:
        """Async wrapper for vacuum()."""
        return await asyncio.to_thread(self.vacuum)
    
    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None
            logger.info("Database connection closed")
    
    async def async_close(self):
        """Async wrapper for close()."""
        await asyncio.to_thread(self.close)
