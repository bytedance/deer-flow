import json
from dataclasses import asdict
from pathlib import Path

from .models import CodingTask, TaskStatus


class JsonTaskStore:
    """把合法任务保存成JSON，并从JSON恢复"""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _task_path(self, task_id: str) -> Path:
        return self.root / f"{task_id}.json"

    def save(self, task: CodingTask) -> None:
        task_dict = asdict(task)
        task_json = json.dumps(task_dict, ensure_ascii=False, indent=2)
        self._task_path(task.id).write_text(task_json, encoding="utf-8")

    def load(self, task_id: str) -> CodingTask:
        task_json = self._task_path(task_id).read_text(encoding="utf-8")
        data = json.loads(task_json)
        data["status"] = TaskStatus(data["status"])
        return CodingTask(**data)

    def list_all(self) -> list[CodingTask]:
        paths = sorted(self.root.glob("*.json"))
        tasks = list()
        for path in paths:
            tasks.append(self.load(path.stem))
        return tasks
