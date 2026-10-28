from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ReviewAction = Literal["edit", "quantity_rule", "verify", "accept", "remove", "restore"]


class ReviewOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operationId: str = Field(min_length=1, max_length=100)
    expectedRevision: int = Field(ge=0)
    action: ReviewAction
    itemIds: list[int] = Field(default_factory=list, max_length=10000)
    issueIds: list[str] = Field(default_factory=list, max_length=10000)
    changes: dict = Field(default_factory=dict)
    itemChanges: dict[int, dict] = Field(default_factory=dict)
    rule: Literal["requested_total", "pack_calculation"] | None = None


class UndoOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operationId: str = Field(min_length=1, max_length=100)
    expectedRevision: int = Field(ge=0)
