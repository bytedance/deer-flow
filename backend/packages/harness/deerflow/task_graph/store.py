import json
from dataclasses import asdict
from pathlib import Path

from .models import CodingRunPlan, CodingTask, TaskStatus


class JsonTaskStore:
    """把合法任务保存成JSON，并从JSON恢复"""

    _RUN_PLAN_FILENAME = "coding-run-plan.json"

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _task_path(self, task_id: str) -> Path:
        return self.root / f"{task_id}.json"

    @property
    def _run_plan_path(self) -> Path:
        return self.root / self._RUN_PLAN_FILENAME

    def save_run_plan(self, plan: CodingRunPlan) -> None:
        self._run_plan_path.write_text(
            json.dumps(asdict(plan), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load_run_plan(self) -> CodingRunPlan:
        data = json.loads(self._run_plan_path.read_text(encoding="utf-8"))
        return CodingRunPlan(**data)

    def save(self, task: CodingTask) -> None:
        task_dict = asdict(task)
        task_json = json.dumps(task_dict, ensure_ascii=False, indent=2)
        self._task_path(task.id).write_text(task_json, encoding="utf-8")

    def load(self, task_id: str) -> CodingTask:
        task_json = self._task_path(task_id).read_text(encoding="utf-8")
        data = json.loads(task_json)
        # 兼容早期持久化任务：failure_reason 在恢复后曾被清空，现改为保留最近失败原因。
        if "last_failure_reason" not in data and "failure_reason" in data:
            data["last_failure_reason"] = data.pop("failure_reason")
        data["status"] = TaskStatus(data["status"])
        return CodingTask(**data)

    def list_all(self) -> list[CodingTask]:
        paths = sorted(path for path in self.root.glob("*.json") if path.name != self._RUN_PLAN_FILENAME)
        tasks = list()
        for path in paths:
            tasks.append(self.load(path.stem))
        return tasks
