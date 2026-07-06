from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class FieldRule(BaseModel):
    field_type: str = Field(..., description="Expected data type")
    is_requried: bool = Field(default=True)
    enum_values: Optional[List[Any]] = Field(default=None)
    data_format: Optional[str] = Field(default=None)
    min_value: Optional[int] = Field(default=None)


