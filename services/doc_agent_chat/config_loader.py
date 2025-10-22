import yaml
import os


class ConfigLoader:
    def __init__(self, config_path: str):
        self.config_path = config_path
        self.config = self.load_yaml(config_path)

    def load_yaml(self, path: str) -> dict:
        with open(path, 'r') as file:
            return yaml.safe_load(file)

    def get(self, key: str, default=None):
        return self.config.get(key, default)
