import pytest
import os
import tempfile
import yaml
from config_loader import load_config, validate_config

def test_load_config_file_not_found():
    with pytest.raises(FileNotFoundError):
        load_config("nonexistent.yaml")

def test_load_config_invalid_yaml():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write("invalid: [yaml: content")
        path = f.name
    try:
        with pytest.raises(yaml.YAMLError):
            load_config(path)
    finally:
        os.unlink(path)

def test_validate_config_missing_strategies():
    config = {"notify": {}}
    errors = validate_config(config)
    assert len(errors) > 0
    assert any("strategies" in e for e in errors)

def test_validate_config_missing_notify():
    config = {"strategies": {}}
    errors = validate_config(config)
    assert len(errors) > 0
    assert any("notify" in e for e in errors)

def test_validate_config_valid():
    config = {
        "strategies": {"bond_ipo": {"enabled": True}},
        "notify": {"desktop": {"enabled": True}},
    }
    errors = validate_config(config)
    assert len(errors) == 0
