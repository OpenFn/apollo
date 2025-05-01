import os
from .config_loader import ConfigLoader

base_dir = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.join(base_dir, "gen_project_config.yaml")
prompts_path = os.path.join(base_dir, "gen_project_prompts.yaml")

config_loader = ConfigLoader(config_path=config_path, prompts_path=prompts_path)
config = config_loader.config

get_info_gen_yaml_system_prompt = config_loader.get_prompt("get_info_gen_yaml_system_prompt")

def build_prompt(content, history):
    system_message = get_info_gen_yaml_system_prompt

    prompt = []
    prompt.extend(history)
    prompt.append({"role": "user", "content": content})
      
    return (system_message, prompt)