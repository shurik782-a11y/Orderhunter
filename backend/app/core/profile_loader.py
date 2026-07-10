from pathlib import Path

import yaml

from app.config import get_settings
from app.core.matcher import ProfileData


def get_config_dir() -> Path:
    settings = get_settings()
    return Path(settings.config_dir).resolve()


def load_profile() -> ProfileData:
    config_dir = get_config_dir()
    profile = ProfileData.load(config_dir)
    profile.data["_config_dir"] = str(config_dir)
    return profile
