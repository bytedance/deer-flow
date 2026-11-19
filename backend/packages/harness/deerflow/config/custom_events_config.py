"""Configuration for the internal ``custom`` LangGraph stream channel."""

from pydantic import BaseModel, Field


class CustomEventsConfig(BaseModel):
    """Config section for the internal ``custom`` stream channel.

    Every run subscribes ``custom`` so middlewares and tools can report progress
    through ``langgraph.config.get_stream_writer()``. DeerFlow's own progress
    events ride on that channel too - the ``task_*`` lifecycle updates, the LLM
    retry hints and the safety finish-reason notice - so turning it off drops
    those as well. Leave it on unless the deployment has no progress consumer
    and wants a strictly caller-defined stream.
    """

    enabled: bool = Field(
        default=True,
        description="Subscribe the internal `custom` stream channel for every run.",
    )
