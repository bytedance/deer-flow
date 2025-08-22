from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class Conversation(BaseModel):
    id: Optional[str] = Field("", description="The thread ID of the conversation.")
    title: Optional[str] = Field("", description="The title of the conversation")
    date: Optional[datetime] = Field(
        "", description="The date of the conversation, formatted as 'YYYY-MM-DD'."
    )

    category: Optional[str] = Field(
        "Social Media", description="The writing style of the conversation."
    )
    count: Optional[int] = Field(
        0, description="The number of messages in the conversation."
    )
    data_type: Optional[str] = Field(
        "txt", description="The type of data in the conversation, e.g., 'txt', 'json'."
    )


class ConversationsResponse(BaseModel):

    data: Optional[list[Conversation]] = Field(
        default_factory=list,
        description="List of replays matching the request criteria",
    )


class ConversationsRequest(BaseModel):
    """Request model for RAG resource queries.

    This model represents a request to search for resources within the RAG system.
    It encapsulates the search query and any associated parameters.

    Attributes:
        query: The search query string used to find relevant resources.
               Can be None if no specific query is provided.
    """

    limit: Optional[int] = Field(
        None, description="The maximum number of resources to retrieve"
    )
    offset: Optional[int] = Field(
        None,
        description="The offset for pagination, used to skip a number of resources",
    )
    sort: Optional[str] = Field(
        None, description="The field by which to sort the resources"
    )
