"""Comprehensive unit and integration tests for FileTask."""

import tempfile
import unittest
from pathlib import Path

from forge import (
    Engine,
    ExecutionContext,
    FailureStrategy,
    FileOperation,
    FileTask,
    FunctionTask,
    TaskStatus,
    Workflow,
)


class TestFileTask(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_path = Path(self.temp_dir.name)
        self.engine = Engine(verbose=False)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_write_and_read(self):
        target = self.base_path / "subdir" / "greeting.txt"

        t_write = FileTask("Write", operation="write", path=target, content="Hello Forge!")
        t_read = FileTask("Read", operation="read", path=target)

        t_write >> t_read

        wf = Workflow("Write & Read WF").add_task(t_read)
        result = self.engine.run(wf)

        self.assertTrue(result.is_success)
        self.assertTrue(target.exists())
        self.assertEqual(result.get_task_result("Read").output, "Hello Forge!")

    def test_append(self):
        target = self.base_path / "log.txt"

        t_write = FileTask("Write", operation="write", path=target, content="Line 1\n")
        t_append = FileTask("Append", operation="append", path=target, content="Line 2\n")
        t_read = FileTask("Read", operation="read", path=target)

        t_write >> t_append >> t_read

        wf = Workflow("Append WF").add_task(t_read)
        result = self.engine.run(wf)

        self.assertTrue(result.is_success)
        self.assertEqual(result.get_task_result("Read").output, "Line 1\nLine 2\n")

    def test_copy_and_move(self):
        src = self.base_path / "original.txt"
        copied = self.base_path / "copied.txt"
        moved = self.base_path / "moved.txt"

        src.write_text("file payload", encoding="utf-8")

        t_copy = FileTask("Copy", operation="copy", source=src, destination=copied)
        t_move = FileTask("Move", operation="move", source=copied, destination=moved)

        t_copy >> t_move

        wf = Workflow("Copy Move WF").add_task(t_move)
        result = self.engine.run(wf)

        self.assertTrue(result.is_success)
        self.assertTrue(src.exists())
        self.assertFalse(copied.exists())
        self.assertTrue(moved.exists())
        self.assertEqual(moved.read_text(encoding="utf-8"), "file payload")

    def test_exists_and_delete(self):
        target = self.base_path / "to_delete.txt"
        target.write_text("temporary", encoding="utf-8")

        t_check_before = FileTask("Check1", operation="exists", path=target)
        t_delete = FileTask("Delete", operation="delete", path=target)
        t_check_after = FileTask("Check2", operation="exists", path=target)

        t_check_before >> t_delete >> t_check_after

        wf = Workflow("Exists Delete WF").add_task(t_check_after)
        result = self.engine.run(wf)

        self.assertTrue(result.is_success)
        self.assertTrue(result.get_task_result("Check1").output)
        self.assertFalse(result.get_task_result("Check2").output)
        self.assertFalse(target.exists())

    def test_upstream_data_flow_to_file(self):
        """Test FunctionTask producing structured data and FileTask saving it automatically."""
        def produce_payload():
            return {"user": "alice", "roles": ["admin", "editor"], "active": True}

        target = self.base_path / "user.json"

        t_func = FunctionTask("GenData", fn=produce_payload)
        t_file = FileTask("SaveJSON", operation="write", path=target)

        # Wire dependency
        t_func >> t_file

        wf = Workflow("Upstream File WF").add_task(t_file)
        result = self.engine.run(wf)

        self.assertTrue(result.is_success)
        self.assertTrue(target.exists())
        content = target.read_text(encoding="utf-8")
        self.assertIn('"user": "alice"', content)
        self.assertIn('"roles"', content)

    def test_binary_read_and_write(self):
        target = self.base_path / "data.bin"
        raw_bytes = b"\x00\xFF\xAA\x55"

        t_write = FileTask(
            "WriteBin", operation="write", path=target, content=raw_bytes, binary=True
        )
        t_read = FileTask("ReadBin", operation="read", path=target, binary=True)

        t_write >> t_read

        wf = Workflow("Binary WF").add_task(t_read)
        result = self.engine.run(wf)

        self.assertTrue(result.is_success)
        self.assertEqual(result.get_task_result("ReadBin").output, raw_bytes)

    def test_validation_errors(self):
        # Read without source/path
        with self.assertRaises(ValueError):
            FileTask("BadRead", operation="read")

        # Copy without destination
        with self.assertRaises(ValueError):
            FileTask("BadCopy", operation="copy", source="a.txt")

        # Invalid operation name
        with self.assertRaises(ValueError):
            FileTask("BadOp", operation="teleport", path="a.txt")

    def test_file_not_found_failure(self):
        non_existent = self.base_path / "ghost.txt"
        task = FileTask("ReadGhost", operation="read", path=non_existent)

        wf = Workflow("Missing File WF").add_task(task)
        result = self.engine.run(wf)

        self.assertTrue(result.is_failed)
        tr = result.get_task_result("ReadGhost")
        self.assertTrue(tr.is_failed)
        self.assertIn("File not found", tr.error_message)


if __name__ == "__main__":
    unittest.main()
