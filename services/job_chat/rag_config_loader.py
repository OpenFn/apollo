import yaml

class ConfigLoader:
    def __init__(self, config_path="rag_config.yaml", prompts_path="rag_prompts.yaml"):
        self.config = self.load_yaml(config_path)
        self.prompts = self.load_yaml(prompts_path)

    def load_yaml(self, path):
        with open(path, "r") as file:
            return yaml.safe_load(file)

    def get_prompt(self, name, **kwargs):
        """Fetches a named prompt and formats it with provided arguments."""
        prompt_template = self.prompts["prompts"].get(name)
        return prompt_template.format(**kwargs)
