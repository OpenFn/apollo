"""Configuration loader for global agent."""
import os
import yaml
from pathlib import Path


class ConfigLoader:
    """Loads and manages configuration from YAML files."""

    def __init__(self, config_path: str = "config.yaml"):
        """
        Initialize config loader.

        Args:
            config_path: Path to config file relative to this module
        """
        # Get directory where this file lives
        module_dir = Path(__file__).parent
        full_path = module_dir / config_path

        if not full_path.exists():
            raise FileNotFoundError(f"Config file not found: {full_path}")

        with open(full_path, 'r') as f:
            self.config = yaml.safe_load(f)

    def get(self, key: str, default=None):
        """Get config value by key."""
        return self.config.get(key, default)

    def __getitem__(self, key: str):
        """Allow dict-style access."""
        return self.config[key]
