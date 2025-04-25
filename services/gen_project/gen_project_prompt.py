import os
from .gen_project import ConfigLoader

base_dir = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.join(base_dir, "rag.yaml")
prompts_path = os.path.join(base_dir, "rag_prompts.yaml")

config_loader = ConfigLoader(config_path=config_path, prompts_path=prompts_path)
config = config_loader.config

get_info_gen_yaml_system_prompt = config_loader.get_prompt("get_info_gen_yaml_system_prompt")

# get_info_gen_yaml_user_prompt = """The user's automation task is as follows: "{user_question}" """

def build_prompt(content, history, context):
    system_message = get_info_gen_yaml_system_prompt

    prompt = []
    prompt.extend(history)
    prompt.append({"role": "user", "content": content})
      
    return (system_message, prompt)