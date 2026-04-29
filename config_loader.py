import yaml
from typing import Any

REQUIRED_SECTIONS = ["strategies", "notify"]

def load_config(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    if config is None:
        config = {}
    errors = validate_config(config)
    if errors:
        raise ValueError(f"配置校验失败: {'; '.join(errors)}")
    return config

def validate_config(config: dict[str, Any]) -> list[str]:
    errors = []
    for section in REQUIRED_SECTIONS:
        if section not in config:
            errors.append(f"缺少必填配置段: {section}")
    return errors
