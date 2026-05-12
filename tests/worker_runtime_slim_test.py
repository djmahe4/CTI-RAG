import builtins
import importlib.util
import sys
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]


def test_task_worker_boot_does_not_import_non_task_workers(monkeypatch):
    worker_path = ROOT / "worker.py"

    fake_task_module = ModuleType("rag.mq.task_worker")

    class FakeTaskWorker:
        started = False

        def run(self):
            FakeTaskWorker.started = True

    fake_task_module.TaskWorker = FakeTaskWorker
    monkeypatch.setitem(sys.modules, "rag.mq.task_worker", fake_task_module)
    sys.modules.pop("rag.mq.conversation_worker", None)
    sys.modules.pop("rag.mq.vector_search_worker", None)

    original_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name in {"rag.mq.conversation_worker", "rag.mq.vector_search_worker"}:
            raise AssertionError(f"unexpected import: {name}")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    monkeypatch.setenv("WORKER_TYPE", "task")
    monkeypatch.setenv("WORKER_COUNT", "1")

    spec = importlib.util.spec_from_file_location("worker_under_test", worker_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    module.main()

    assert FakeTaskWorker.started is True


def test_worker_dockerfile_uses_slim_requirements_file():
    dockerfile_worker = (ROOT / "Dockerfile.worker").read_text(encoding="utf-8")

    assert "COPY requirements-worker.txt ." in dockerfile_worker
    assert "uv pip install --system -r requirements-worker.txt" in dockerfile_worker

