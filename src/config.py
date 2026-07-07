import os
from typing import List, Optional
import yaml
from pydantic import BaseModel, Field, HttpUrl


class EmulatorConfig(BaseModel):
    url: HttpUrl
    timeout: int = Field(default=10, ge=1)
    username: Optional[str] = None
    password: Optional[str] = None


class StorageConfig(BaseModel):
    specification_path: str
    output_path: str


class ValidationConfig(BaseModel):
    resources_filter: List[str] = Field(default_factory=list)


class AppConfig(BaseModel):
    emulator: EmulatorConfig
    storage: StorageConfig
    validator: ValidationConfig


def load_config(config_path: str = "config/config.yml") -> AppConfig:

    if not os.path.exists(config_path):
        raise FileNotFoundError("No config")
    
    with open(config_path, "r", encoding="utf-8") as f:
        config_data = yaml.safe_load(f)
    
    if "auth" in config_data.get("emulator", {}):
        auth = config_data["emulator"]["auth"]
        config_data["emulator"]["username"] = auth.get("username")
        config_data["emulator"]["password"] = auth.get("password")
    
    return AppConfig(**config_data)
       
