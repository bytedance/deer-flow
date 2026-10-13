"""Fixed operator-authorized workers; never populated from model arguments."""

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Node(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    cpu_millis: int = Field(gt=0)
    memory_mib: int = Field(gt=0)
    resident_cpu_millis: int = Field(ge=0)
    resident_memory_mib: int = Field(ge=0)
    max_concurrency: int = Field(gt=0)
    profiles: set[str]
    kinds: set[str] = {"B"}
    drain: bool = False
    worker_version: str = "0.1.0"

    @model_validator(mode="after")
    def capacity(self):
        if self.resident_cpu_millis > self.cpu_millis or self.resident_memory_mib > self.memory_mib or not self.kinds <= {"B", "C"}:
            raise ValueError("Invalid node capacity or execution kinds")
        return self
