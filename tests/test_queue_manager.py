import json
import copy
import pytest
from datetime import datetime, timedelta
from pathlib import Path


class TestInit:
    def test_creates_table_and_directory(self, tmp_path):
        db_path = tmp_path / "growmate" / "queue.db"
        from queue_manager import QueueManager
        qm = QueueManager(db_path)
        assert qm.initialize() is True
        assert db_path.exists()
        conn = qm._get_connection()
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        names = {r["name"] for r in tables}
        assert "sensor_queue" in names
        assert "queue_metadata" in names
        qm.close()

    def test_uses_provided_db_path(self, tmp_path):
        db_path = tmp_path / "custom_path.db"
        from queue_manager import QueueManager
        qm = QueueManager(db_path)
        assert qm.db_path == db_path
        qm.close()

    def test_initialize_idempotent(self, tmp_path):
        from queue_manager import QueueManager
        qm = QueueManager(tmp_path / "q.db")
        assert qm.initialize() is True
        assert qm.initialize() is True
        qm.close()

    def test_max_sensor_entries_default(self, tmp_path):
        from queue_manager import QueueManager
        qm = QueueManager(tmp_path / "q.db")
        assert qm.max_sensor_entries == 6000
        qm.close()

    def test_max_sensor_entries_custom(self, tmp_path):
        from queue_manager import QueueManager
        qm = QueueManager(tmp_path / "q.db", max_sensor_entries=100)
        assert qm.max_sensor_entries == 100
        qm.close()


class TestEnqueueSensorData:
    @pytest.fixture
    def qm(self, tmp_path):
        from queue_manager import QueueManager
        qm = QueueManager(tmp_path / "q.db")
        qm.initialize()
        yield qm
        qm.close()

    def test_enqueue_inserts_row(self, qm):
        assert qm.enqueue_sensor_data(
            "device-1", "2.0.0",
            [{"type": "temperature", "value": 25.0}],
            {"status": "ok"}
        ) is True
        assert qm.get_queue_stats()["sensor_queue"]["total"] == 1

    def test_enqueue_with_multiple_sensors(self, qm):
        sensors = [
            {"type": "temperature", "value": 25.0},
            {"type": "humidity", "value": 60.0},
        ]
        assert qm.enqueue_sensor_data("d1", "2.0.0", sensors, {}) is True
        stats = qm.get_queue_stats()
        assert stats["sensor_queue"]["total"] == 1

    def test_enqueue_stores_json(self, qm):
        sensors = [{"type": "temperature", "value": 25.0}]
        state = {"mode": "auto"}
        qm.enqueue_sensor_data("d1", "2.0.0", sensors, state)
        item = qm.dequeue_next_sensor()
        assert item["sensor_data"] == sensors
        assert item["current_state"] == state

    def test_enqueue_max_entries_drops_oldest(self, tmp_path):
        from queue_manager import QueueManager
        qm = QueueManager(tmp_path / "q2.db", max_sensor_entries=2)
        qm.initialize()
        qm.enqueue_sensor_data("d1", "1", [{"a": 1}], {})
        qm.enqueue_sensor_data("d1", "1", [{"a": 2}], {})
        qm.enqueue_sensor_data("d1", "1", [{"a": 3}], {})
        stats = qm.get_queue_stats()
        assert stats["sensor_queue"]["total"] == 2
        item = qm.dequeue_next_sensor()
        assert item["sensor_data"] == [{"a": 2}]
        qm.close()


class TestDequeueNextSensor:
    @pytest.fixture
    def qm(self, tmp_path):
        from queue_manager import QueueManager
        qm = QueueManager(tmp_path / "q.db")
        qm.initialize()
        qm.enqueue_sensor_data("d1", "1", [{"v": 1}], {})
        qm.enqueue_sensor_data("d1", "1", [{"v": 2}], {})
        yield qm
        qm.close()

    def test_dequeue_fifo(self, qm):
        item1 = qm.dequeue_next_sensor()
        assert item1["sensor_data"] == [{"v": 1}]
        item2 = qm.dequeue_next_sensor()
        assert item2["sensor_data"] == [{"v": 2}]

    def test_dequeue_empty_returns_none(self, qm):
        qm.dequeue_next_sensor()
        qm.dequeue_next_sensor()
        assert qm.dequeue_next_sensor() is None

    def test_dequeue_sets_status_uploading(self, qm):
        item = qm.dequeue_next_sensor()
        assert item is not None
        conn = qm._get_connection()
        row = conn.execute(
            "SELECT status FROM sensor_queue WHERE id = ?", (item["id"],)
        ).fetchone()
        assert row["status"] == "uploading"

    def test_dequeue_returns_parsed_json(self, qm):
        item = qm.dequeue_next_sensor()
        assert isinstance(item["sensor_data"], list)
        assert isinstance(item["current_state"], dict)

    def test_dequeue_includes_retry_count(self, qm):
        item = qm.dequeue_next_sensor()
        assert "retry_count" in item
        assert item["retry_count"] == 0


class TestMarkSensor:
    @pytest.fixture
    def qm(self, tmp_path):
        from queue_manager import QueueManager
        qm = QueueManager(tmp_path / "q.db")
        qm.initialize()
        qm.enqueue_sensor_data("d1", "1", [{"v": 1}], {})
        yield qm
        qm.close()

    def test_mark_uploaded_deletes_row(self, qm):
        item = qm.dequeue_next_sensor()
        assert qm.mark_sensor_uploaded(item["id"]) is True
        assert qm.dequeue_next_sensor() is None

    def test_mark_uploaded_updates_metadata(self, qm):
        item = qm.dequeue_next_sensor()
        qm.mark_sensor_uploaded(item["id"])
        stats = qm.get_queue_stats()
        assert stats["metadata"]["total_sensor_uploads"] == "1"

    def test_mark_failed_retries_pending(self, qm):
        item = qm.dequeue_next_sensor()
        assert qm.mark_sensor_failed(item["id"], max_retries=5) is True
        conn = qm._get_connection()
        row = conn.execute(
            "SELECT status, retry_count FROM sensor_queue WHERE id = ?",
            (item["id"],)
        ).fetchone()
        assert row["status"] == "pending"
        assert row["retry_count"] == 1

    def test_mark_failed_exceeds_retries_deletes(self, qm):
        item = qm.dequeue_next_sensor()
        qm.mark_sensor_failed(item["id"], max_retries=1)
        conn = qm._get_connection()
        row = conn.execute(
            "SELECT COUNT(*) as c FROM sensor_queue WHERE id = ?",
            (item["id"],)
        ).fetchone()
        assert row["c"] == 0

    def test_mark_failed_updates_failure_metadata(self, qm):
        item = qm.dequeue_next_sensor()
        qm.mark_sensor_failed(item["id"], max_retries=1)
        stats = qm.get_queue_stats()
        assert stats["metadata"]["total_failures"] == "1"

    def test_mark_failed_nonexistent_id(self, qm):
        assert qm.mark_sensor_failed(99999) is False


class TestQueueStats:
    @pytest.fixture
    def qm(self, tmp_path):
        from queue_manager import QueueManager
        qm = QueueManager(tmp_path / "q.db")
        qm.initialize()
        yield qm
        qm.close()

    def test_stats_empty_queue(self, qm):
        stats = qm.get_queue_stats()
        assert stats["sensor_queue"]["total"] == 0

    def test_stats_with_items(self, qm):
        qm.enqueue_sensor_data("d1", "1", [{}], {})
        qm.enqueue_sensor_data("d2", "1", [{}], {})
        stats = qm.get_queue_stats()
        assert stats["sensor_queue"]["total"] == 2
        assert stats["sensor_queue"]["pending"] == 2

    def test_stats_contains_metadata(self, qm):
        stats = qm.get_queue_stats()
        assert "metadata" in stats
        assert stats["metadata"]["schema_version"] == "2"


class TestCleanup:
    @pytest.fixture
    def qm(self, tmp_path):
        from queue_manager import QueueManager
        qm = QueueManager(tmp_path / "q.db")
        qm.initialize()
        qm.enqueue_sensor_data("d1", "1", [{}], {})
        conn = qm._get_connection()
        conn.execute(
            "UPDATE sensor_queue SET created_at = '2020-01-01 00:00:00'"
        )
        conn.commit()
        yield qm
        qm.close()

    def test_cleanup_removes_old_entries(self, qm):
        removed = qm.cleanup_old_entries(max_age_hours=1)
        assert removed > 0
        assert qm.get_queue_stats()["sensor_queue"]["total"] == 0

    def test_cleanup_recent_entries_preserved(self, tmp_path):
        from queue_manager import QueueManager
        qm = QueueManager(tmp_path / "q.db")
        qm.initialize()
        qm.enqueue_sensor_data("d1", "1", [{}], {})
        removed = qm.cleanup_old_entries(max_age_hours=24)
        assert removed == 0
        qm.close()

    def test_cleanup_empty_queue(self, tmp_path):
        from queue_manager import QueueManager
        qm = QueueManager(tmp_path / "q.db")
        qm.initialize()
        assert qm.cleanup_old_entries() == 0
        qm.close()


class TestVacuum:
    def test_vacuum_succeeds(self, tmp_path):
        from queue_manager import QueueManager
        qm = QueueManager(tmp_path / "q.db")
        qm.initialize()
        assert qm.vacuum() is True
        qm.close()


class TestClose:
    def test_close_sets_conn_to_none(self, tmp_path):
        from queue_manager import QueueManager
        qm = QueueManager(tmp_path / "q.db")
        qm.initialize()
        assert qm.conn is not None
        qm.close()
        assert qm.conn is None

    def test_close_idempotent(self, tmp_path):
        from queue_manager import QueueManager
        qm = QueueManager(tmp_path / "q.db")
        qm.initialize()
        qm.close()
        qm.close()


class TestAsyncMethods:
    @pytest.mark.asyncio
    async def test_async_initialize(self, tmp_path):
        from queue_manager import QueueManager
        qm = QueueManager(tmp_path / "async.db")
        assert await qm.async_initialize() is True
        qm.close()

    @pytest.mark.asyncio
    async def test_async_enqueue_dequeue(self, tmp_path):
        from queue_manager import QueueManager
        qm = QueueManager(tmp_path / "async2.db")
        await qm.async_initialize()
        assert await qm.async_enqueue_sensor_data("d1", "1", [{"x": 1}], {}) is True
        item = await qm.async_dequeue_next_sensor()
        assert item is not None
        assert item["sensor_data"] == [{"x": 1}]
        qm.close()

    @pytest.mark.asyncio
    async def test_async_mark_uploaded(self, tmp_path):
        from queue_manager import QueueManager
        qm = QueueManager(tmp_path / "async3.db")
        await qm.async_initialize()
        await qm.async_enqueue_sensor_data("d1", "1", [{}], {})
        item = await qm.async_dequeue_next_sensor()
        assert await qm.async_mark_sensor_uploaded(item["id"]) is True
        qm.close()

    @pytest.mark.asyncio
    async def test_async_mark_failed(self, tmp_path):
        from queue_manager import QueueManager
        qm = QueueManager(tmp_path / "async4.db")
        await qm.async_initialize()
        await qm.async_enqueue_sensor_data("d1", "1", [{}], {})
        item = await qm.async_dequeue_next_sensor()
        assert await qm.async_mark_sensor_failed(item["id"], max_retries=1) is True
        qm.close()

    @pytest.mark.asyncio
    async def test_async_get_stats_and_close(self, tmp_path):
        from queue_manager import QueueManager
        qm = QueueManager(tmp_path / "async5.db")
        await qm.async_initialize()
        stats = await qm.async_get_queue_stats()
        assert stats["sensor_queue"]["total"] == 0
        await qm.async_close()


class TestSqliteErrors:
    def test_initialize_sqlite_error(self, tmp_path, mocker):
        import sqlite3
        from queue_manager import QueueManager
        qm = QueueManager(tmp_path / "q.db")
        mocker.patch.object(qm, "_get_connection", side_effect=sqlite3.Error("fail"))
        assert qm.initialize() is False
        qm.close()

    def test_enqueue_sensor_data_sqlite_error(self, tmp_path, mocker):
        import sqlite3
        from queue_manager import QueueManager
        qm = QueueManager(tmp_path / "q.db")
        qm.initialize()
        mocker.patch.object(qm, "_get_connection", side_effect=sqlite3.Error("fail"))
        assert qm.enqueue_sensor_data("d1", "1", [{}], {}) is False
        qm.close()

    def test_dequeue_next_sensor_sqlite_error(self, tmp_path, mocker):
        import sqlite3
        from queue_manager import QueueManager
        qm = QueueManager(tmp_path / "q.db")
        qm.initialize()
        qm.enqueue_sensor_data("d1", "1", [{"v": 1}], {})
        mocker.patch.object(qm, "_get_connection", side_effect=sqlite3.Error("fail"))
        assert qm.dequeue_next_sensor() is None
        qm.close()

    def test_mark_sensor_uploaded_sqlite_error(self, tmp_path, mocker):
        import sqlite3
        from queue_manager import QueueManager
        qm = QueueManager(tmp_path / "q.db")
        qm.initialize()
        qm.enqueue_sensor_data("d1", "1", [{}], {})
        item = qm.dequeue_next_sensor()
        mocker.patch.object(qm, "_get_connection", side_effect=sqlite3.Error("fail"))
        assert qm.mark_sensor_uploaded(item["id"]) is False
        qm.close()

    def test_mark_sensor_failed_sqlite_error(self, tmp_path, mocker):
        import sqlite3
        from queue_manager import QueueManager
        qm = QueueManager(tmp_path / "q.db")
        qm.initialize()
        qm.enqueue_sensor_data("d1", "1", [{}], {})
        item = qm.dequeue_next_sensor()
        mocker.patch.object(qm, "_get_connection", side_effect=sqlite3.Error("fail"))
        assert qm.mark_sensor_failed(item["id"]) is False
        qm.close()

    def test_get_queue_stats_sqlite_error(self, tmp_path, mocker):
        import sqlite3
        from queue_manager import QueueManager
        qm = QueueManager(tmp_path / "q.db")
        qm.initialize()
        mocker.patch.object(qm, "_get_connection", side_effect=sqlite3.Error("fail"))
        assert qm.get_queue_stats() == {}
        qm.close()

    def test_cleanup_old_entries_sqlite_error(self, tmp_path, mocker):
        import sqlite3
        from queue_manager import QueueManager
        qm = QueueManager(tmp_path / "q.db")
        qm.initialize()
        mocker.patch.object(qm, "_get_connection", side_effect=sqlite3.Error("fail"))
        assert qm.cleanup_old_entries() == 0
        qm.close()

    def test_vacuum_sqlite_error(self, tmp_path, mocker):
        import sqlite3
        from queue_manager import QueueManager
        qm = QueueManager(tmp_path / "q.db")
        qm.initialize()
        mocker.patch.object(qm, "_get_connection", side_effect=sqlite3.Error("fail"))
        assert qm.vacuum() is False
        qm.close()


class TestAsyncMethodsSync:
    def test_async_cleanup_old_entries(self, tmp_path):
        import asyncio
        from datetime import datetime, timedelta
        from queue_manager import QueueManager
        qm = QueueManager(tmp_path / "async_cleanup.db")
        qm.initialize()
        qm.enqueue_sensor_data("d1", "1", [{}], {})
        conn = qm._get_connection()
        conn.execute("UPDATE sensor_queue SET created_at = '2020-01-01'")
        conn.commit()
        result = asyncio.run(qm.async_cleanup_old_entries(max_age_hours=1))
        assert result > 0
        qm.close()

    def test_async_vacuum(self, tmp_path):
        import asyncio
        from queue_manager import QueueManager
        qm = QueueManager(tmp_path / "async_vacuum.db")
        qm.initialize()
        result = asyncio.run(qm.async_vacuum())
        assert result is True
        qm.close()
