"""DataEase Skill 2.1 core package."""

from .config import Settings
from .client import DataEaseClient
from .errors import DataEaseError

__all__ = ["DataEaseClient", "DataEaseError", "Settings"]
__version__ = "2.1.0"
