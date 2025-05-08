import os
from .config_loader import ConfigLoader

base_dir = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.join(base_dir, "gen_project_config.yaml")
prompts_path = os.path.join(base_dir, "gen_project_prompts.yaml")

config_loader = ConfigLoader(config_path=config_path, prompts_path=prompts_path)
config = config_loader.config

def chat_prompt(content, existing_yaml, history):
    if not existing_yaml:
        existing_yaml = ""
    else:
        existing_yaml = "\nFor context, the user is currently editing this YAML:\n" + existing_yaml
    
    system_message = config_loader.get_prompt("get_info_gen_yaml_system_prompt")
    system_message += existing_yaml

    prompt = []
    prompt.extend(history)
    prompt.append({"role": "user", "content": content})
      
    return (system_message, prompt)

def error_prompt(content, existing_yaml, errors, history):
    if not existing_yaml:
        existing_yaml = ""
    else:
        existing_yaml = "\nThis is the YAML causing the error:\n" + existing_yaml

    if not content:
        content = ""
    
    system_message = config_loader.get_prompt("fix_yaml_error_system_prompt")
    system_message += existing_yaml
    content += "\nThis is the error message:\n" + errors
    
    prompt = []
    prompt.extend(history)
    prompt.append({"role": "user", "content": content})
      
    return (system_message, prompt)

def build_prompt(content, existing_yaml, errors, history):
    if errors:
        return error_prompt(content, existing_yaml, errors, history)
    else:
        return chat_prompt(content, existing_yaml, history)