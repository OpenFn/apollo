"""Configuration loader for global agent."""
import os
import yaml
from pathlib import Path


class ConfigLoader:
    """Loads and manages configuration from YAML files."""

    def __init__(self, config_path: str = "config.yaml", prompts_path: str = "prompts.yaml"):
        """
        Initialize config loader.

        Args:
            config_path: Path to config file relative to this module
            prompts_path: Path to prompts file relative to this module
        """
        # Get directory where this file lives
        module_dir = Path(__file__).parent

        # Load config
        full_config_path = module_dir / config_path
        if not full_config_path.exists():
            raise FileNotFoundError(f"Config file not found: {full_config_path}")

        with open(full_config_path, 'r') as f:
            self.config = yaml.safe_load(f)

        # Load prompts
        full_prompts_path = module_dir / prompts_path
        if not full_prompts_path.exists():
            raise FileNotFoundError(f"Prompts file not found: {full_prompts_path}")

        with open(full_prompts_path, 'r') as f:
            self.prompts = yaml.safe_load(f)

    def get(self, key: str, default=None):
        """Get config value by key."""
        return self.config.get(key, default)

    def get_prompt(self, prompt_key: str) -> str:
        """Get prompt by key from prompts.yaml."""
        return self.prompts.get("prompts", {}).get(prompt_key, "")

    def __getitem__(self, key: str):
        """Allow dict-style access."""
        return self.config[key]
