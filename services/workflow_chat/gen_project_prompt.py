import os

from name_rules import describe_rule_for_prompt

from .available_adaptors import get_adaptors_string
from .config_loader import ConfigLoader

base_dir = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.join(base_dir, "gen_project_config.yaml")
prompts_path = os.path.join(base_dir, "gen_project_prompts.yaml")

config_loader = ConfigLoader(config_path=config_path, prompts_path=prompts_path)
config = config_loader.config


NAME_RULE_TOKEN = "{name_rule}"


def _general_knowledge():
    """Render the general-knowledge prompt, with the active step-name rule in it.

    `str.format` ignores a keyword the template does not use, so dropping the
    token from the yaml would silently ship a prompt that states no naming rule
    at all while the sanitizer carried on enforcing one. Check for it first.
    """
    rule = describe_rule_for_prompt()
    rendered = config_loader.get_prompt("general_knowledge").format(
        adaptors=get_adaptors_string(),
        name_rule=rule,
    )

    # Check the *rendered* text, not the template. A doubled `{{name_rule}}` is
    # how `.format` escapes a literal brace: it contains the token as a
    # substring, so a template-side check waves it through, and what reaches the
    # model is the four words "{name_rule}" rather than any rule at all.
    if NAME_RULE_TOKEN in rendered or rule not in rendered:
        raise ValueError(
            f"The general_knowledge prompt did not render the step-name rule. It must contain "
            f"exactly {NAME_RULE_TOKEN}, unescaped and unduplicated — the rule stated to the "
            f"model and the rule the sanitizer enforces have to come from the same place.",
        )
    return rendered


def build_system_message(mode_config, existing_yaml=None):
    """Build system message with mode-specific configuration."""
    system_message = config_loader.get_prompt("main_system_prompt").format(
        mode_specific_intro=config_loader.get_prompt(mode_config["intro"]),
        yaml_structure=config_loader.get_prompt(mode_config["yaml_structure"]),
        general_knowledge=_general_knowledge(),
        output_format=config_loader.get_prompt(mode_config["output_format"]),
        mode_specific_answering_instructions=config_loader.get_prompt(
            mode_config["answering_instructions"],
        ),
    )
    
    if existing_yaml:
        system_message += mode_config["yaml_prefix"] + existing_yaml
    
    return system_message


def build_prompt(content, existing_yaml=None, errors=None, history=None, read_only=False, subagent=False):
    """
    Build a prompt for the LLM based on mode and context.

    Args:
        content: User message content
        existing_yaml: Current YAML being edited (optional)
        errors: Error messages if in error mode (optional)
        history: Conversation history (optional)
        read_only: Whether in read-only mode
        subagent: Whether called from global_chat (adds handover instructions)

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
            "yaml_prefix": "\nFor context, the user is viewing this read-only YAML:\n",
        }
        user_content = content
    elif errors:
        mode_config = {
            "intro": "error_mode_intro",
            "yaml_structure": "yaml_structure_with_ids",
            "output_format": "json_output_format",
            "answering_instructions": "error_mode_answering_instructions",
            "yaml_prefix": "\nThis is the YAML causing the error:\n",
        }
        user_content = f"{content}\nThis is the error message:\n{errors}" if content else f"\nThis is the error message:\n{errors}"
    else:
        mode_config = {
            "intro": "normal_mode_intro",
            "yaml_structure": "yaml_structure_with_ids",
            "output_format": "json_output_format",
            "answering_instructions": "normal_mode_answering_instructions",
            "yaml_prefix": "\nFor context, the user is currently editing this YAML:\n",
        }
        user_content = content
    
    system_message = build_system_message(mode_config, existing_yaml)

    if subagent:
        # Job-code requests are handed over instead — remove the decline-and-
        # navigate-to-the-Inspector instruction (it appears in two prompt
        # sections) so it can never slip out. Must match prompts yaml verbatim;
        # a unit test guards against the two drifting apart.
        system_message = system_message.replace(
            "If the user asks for job code, DECLINE to provide it yet, and explain that they "
            "need to save their workflow and then navigate to the specific job's code page in "
            "the Inspector. Once there, you can help them write the code (and will be able to "
            "see any existing code for that job).",
            'If the user asks for job code, set "handover" (see Job Code Requests below).',
        )
        system_message += "\n" + config_loader.get_prompt("subagent_handover_instructions")

    prompt = list(history)  # Create a copy
    prompt.append({"role": "user", "content": user_content})

    return (system_message, prompt)