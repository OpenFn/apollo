import os
from .config_loader import ConfigLoader
from .available_adaptors import get_adaptors_string

base_dir = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.join(base_dir, "gen_project_config.yaml")
prompts_path = os.path.join(base_dir, "gen_project_prompts.yaml")

config_loader = ConfigLoader(config_path=config_path, prompts_path=prompts_path)
config = config_loader.config


def build_system_message(mode_config, existing_yaml=None):
    """Build system message with caching breakpoints as array of content blocks."""

    # Build main prompt without general_knowledge (will add separately)
    main_prompt = config_loader.get_prompt("main_system_prompt").format(
        mode_specific_intro=config_loader.get_prompt(mode_config["intro"]),
        yaml_structure=config_loader.get_prompt(mode_config["yaml_structure"]),
        general_knowledge="",  # Empty - will add as separate block
        output_format=config_loader.get_prompt(mode_config["output_format"]),
        mode_specific_answering_instructions=config_loader.get_prompt(
            mode_config["answering_instructions"]
        )
    )

    # Build as array of content blocks
    message = [{"type": "text", "text": main_prompt}]

    # Cache breakpoint 1: After main system instructions (~1550 tokens)
    message.append({"type": "text", "text": ".", "cache_control": {"type": "ephemeral"}})

    # Add general knowledge with adaptors (quasi-static, ~2500 tokens)
    general_knowledge_section = config_loader.get_prompt("general_knowledge").format(
        adaptors=get_adaptors_string()
    )
    message.append({"type": "text", "text": general_knowledge_section})

    # Cache breakpoint 2: After general knowledge (~4050 tokens total)
    message.append({"type": "text", "text": ".", "cache_control": {"type": "ephemeral"}})

    # Add existing YAML if provided (DYNAMIC - not cached)
    if existing_yaml:
        yaml_context = mode_config["yaml_prefix"] + existing_yaml
        message.append({"type": "text", "text": yaml_context})

    return message


def build_prompt(content, existing_yaml=None, errors=None, history=None, read_only=False):
    """
    Build a prompt for the LLM based on mode and context.
    
    Args:
        content: User message content
        existing_yaml: Current YAML being edited (optional)
        errors: Error messages if in error mode (optional)
        history: Conversation history (optional)
        read_only: Whether in read-only mode
    
    Returns:
        Tuple of (system_message, prompt_messages)
    """
    history = history or []
    
    if read_only:
        mode_config = {
            "intro": "normal_mode_intro",
            "yaml_structure": "yaml_structure_without_ids",
            "output_format": "unstructured_output_format",
            "answering_instructions": "readonly_mode_answering_instructions",
            "yaml_prefix": "\nFor context, the user is viewing this read-only YAML:\n"
        }
        user_content = content
    elif errors:
        mode_config = {
            "intro": "error_mode_intro",
            "yaml_structure": "yaml_structure_with_ids",
            "output_format": "json_output_format",
            "answering_instructions": "error_mode_answering_instructions",
            "yaml_prefix": "\nThis is the YAML causing the error:\n"
        }
        user_content = f"{content}\nThis is the error message:\n{errors}" if content else f"\nThis is the error message:\n{errors}"
    else:
        mode_config = {
            "intro": "normal_mode_intro",
            "yaml_structure": "yaml_structure_with_ids",
            "output_format": "json_output_format",
            "answering_instructions": "normal_mode_answering_instructions",
            "yaml_prefix": "\nFor context, the user is currently editing this YAML:\n"
        }
        user_content = content
    
    system_message = build_system_message(mode_config, existing_yaml)
    
    prompt = list(history)  # Create a copy
    prompt.append({"role": "user", "content": user_content})
    
    return (system_message, prompt)