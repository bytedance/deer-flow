from .models import CodingTask, TaskStatus
from .store import JsonTaskStore


class TaskGraph:
    """管理任务依赖和状态流转规则"""

    def __init__(self, store: JsonTaskStore):
        self.store = store

    def add_tasks(self, tasks: list[CodingTask]) -> list[CodingTask]:
        """接收 Coding Agent 制定的一整批任务计划，确认这份计划合法后，再保存到磁盘。"""
        seen: set[str] = set()
        # 建立字典
        task_map = {task.id: task for task in tasks}
        # 检查重复ID
        for task in tasks:
            if task.id in seen:
                raise ValueError("duplicate task id")
            seen.add(task.id)
            # 检查依赖存在
            for dep_id in task.blocked_by:
                if dep_id not in task_map:
                    raise ValueError("missing dependency")
        # 检查循环依赖
        visiting = set()
        visited = set()

        def check(task_id: str):
            if task_id in visiting:
                raise ValueError("cycle detected")
            if task_id in visited:
                return

            visiting.add(task_id)

            for dep_id in task_map[task_id].blocked_by:
                check(dep_id)

            visiting.remove(task_id)
            visited.add(task_id)

        for task_id in task_map:
            check(task_id)
        for task in tasks:
            self.store.save(task)
        return tasks

    def can_start(self, task_id: str) -> bool:
        """是否可执行"""
        #    加载当前任务
        #   -> 遍历 blocked_by
        #   -> 依赖文件不存在：False
        #   -> 依赖状态不是 completed：False
        #   -> 全部检查通过：True
        task = self.store.load(task_id)
        for dep_id in task.blocked_by:
            try:
                dependency = self.store.load(dep_id)
                if dependency.status != TaskStatus.completed:
                    return False
            except FileNotFoundError:
                return False
        else:
            return True

    def claim(self, task_id: str, owner: str) -> CodingTask:
        """认领任务"""
        # 加载任务
        # -> status 不是 pending：抛出 ValueError
        # -> can_start() 是 False：抛出 ValueError
        # -> 设置 owner
        # -> 状态改成 in_progress
        # -> save()
        # -> 返回修改后的 CodingTask
        task = self.store.load(task_id)
        if task.status is not TaskStatus.pending:
            raise ValueError("task must be pending")
        if not self.can_start(task_id):
            raise ValueError("task is blocked")
        task.owner = owner
        task.status = TaskStatus.in_progress
        self.store.save(task)
        return task

    def fail(self, task_id: str, reason: str) -> CodingTask:
        task = self.store.load(task_id)
        if task.status is not TaskStatus.in_progress:
            raise ValueError("Only in_progress task can fail")
        task.status = TaskStatus.failed
        task.failure_reason = reason
        self.store.save(task)
        return task

    def recover(self, task_id: str) -> CodingTask:
        task = self.store.load(task_id)
        if task.status is not TaskStatus.failed:
            raise ValueError("Only failed task can recover")
        task.status = TaskStatus.pending
        task.owner = None
        task.failure_reason = None
        self.store.save(task)
        return task

    def complete(self, task_id: str) -> list[str]:
        """标记为完成"""
        # 加载任务
        # -> status 不是 in_progress：抛出 ValueError
        # -> 状态改为 completed
        # -> save()
        # -> 扫描所有任务
        # -> 找出刚刚可以执行的下游任务
        # -> 返回这些任务的 ID
        task = self.store.load(task_id)
        if task.status is not TaskStatus.in_progress:
            raise ValueError("task must be in_progress")
        task.status = TaskStatus.completed
        self.store.save(task)
        tasks = self.store.list_all()
        ids = []
        for task in tasks:
            # status 是 pending
            # blocked_by 不是空列表
            # can_start(task.id) 是 True
            if task.status is TaskStatus.pending and task.blocked_by and self.can_start(task.id):
                ids.append(task.id)
        return ids
