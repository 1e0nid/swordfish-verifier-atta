from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

class FieldRule(BaseModel):
    """
    Правило проверки для конкретного поля в JSON-ответе.
    """
    field_type: str = Field(..., description="Ожидаемый тип данных: integer, string, boolean, object, array")
    is_required: bool = Field(default=True, description="Является ли поле обязательным")
    enum_values: Optional[List[Any]] = Field(default=None, description="Список допустимых значений, если это Enum")
    data_format: Optional[str] = Field(default=None, description="Специфичный формат: uuid, date-time (ISO 8601)")
    min_value: Optional[int] = Field(default=None, description="Минимальное допустимое значение (для проверки пограничных значений)")

class ResourceRule(BaseModel):
    """
    Правило проверки для отдельного ресурса или эндпоинта СХД.
    """
    resource_name: str = Field(..., description="Имя ресурса (например, Volumes, Drives)")
    endpoint_path: str = Field(..., description="Относительный путь эндпоинта (например, /redfish/v1/Systems/1)")
    allowed_methods: List[str] = Field(default_factory=lambda: ["GET"], description="Разрешенные HTTP-методы для эндпоинта")
    expected_fields: Dict[str, FieldRule] = Field(
        default_factory=dict, 
        description="Словарь полей, где ключ — путь к полю (например, 'Capacity.ProvisionedBytes'), а значение — правило FieldRule"
    )

class SpecificationRules(BaseModel):
    """
    Полный набор правил, извлеченных из всей спецификации Swordfish.
    """
    specification_version: str = Field(default="Swordfish v1.2.9")
    resources: Dict[str, ResourceRule] = Field(
        default_factory=dict, 
        description="Ключ — тип ресурса (Systems, Volumes и т.д.), значение — правила ResourceRule"
    )