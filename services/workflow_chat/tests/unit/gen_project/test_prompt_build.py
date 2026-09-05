from workflow_chat.gen_project_prompt import build_prompt


def test_build_prompt_normal_mode():
    system_msg, prompt = build_prompt(
        content="Create a workflow",
        existing_yaml="name: test-workflow",
        history=[{"role": "user", "content": "Hello"}],
    )

    assert "talk to a client with the goal of converting" in system_msg
    assert "You can either" in system_msg
    assert "user is currently editing this YAML" in system_msg
    assert "name: test-workflow" in system_msg

    assert len(prompt) == 2
    assert prompt[-1]["content"] == "Create a workflow"


def test_build_prompt_error_mode():
    system_msg, prompt = build_prompt(
        content="Fix the workflow",
        existing_yaml="name: broken-workflow",
        errors="Invalid trigger type",
        history=[],
    )

    assert "Your previous suggestion produced an invalid" in system_msg
    assert "Answer with BOTH the" in system_msg
    assert "YAML causing the error" in system_msg
    assert "name: broken-workflow" in system_msg

    assert prompt[-1]["content"] == "Fix the workflow\nThis is the error message:\nInvalid trigger type"


def test_build_prompt_production_keeps_inspector_instruction():
    system_msg, _ = build_prompt(
        content="Create a workflow",
        existing_yaml="name: test-workflow",
        history=[],
    )

    # Production callers never set subagent: the decline-and-navigate
    # instruction must stay untouched
    assert "navigate to the specific job's code page in the Inspector" in system_msg
    assert "handover" not in system_msg


def test_build_prompt_subagent_strips_inspector_instruction():
    system_msg, _ = build_prompt(
        content="Create a workflow",
        existing_yaml="name: test-workflow",
        history=[],
        subagent=True,
    )

    # The go-elsewhere phrasing must not be in context at all, in any of the
    # prompt sections it appears in — if this fails, the sentence in
    # gen_project_prompts.yaml and the replace() in build_prompt have drifted
    assert "navigate to the specific job's code page in the Inspector" not in system_msg
    assert "DECLINE" not in system_msg
    assert 'If the user asks for job code, set "handover"' in system_msg
    assert "Job Code Requests" in system_msg


def test_build_prompt_attaches_input_to_the_current_turn_only():
    log = "[R/T] Job exited with error code 1"

    system_msg, prompt = build_prompt(
        content="add a retry step",
        existing_yaml="name: test-workflow",
        history=[{"role": "user", "content": "hello"}],
        attachments=[{"type": "log", "content": log}],
    )

    # Rendered verbatim at the end of the system message, where this service's
    # other context already lives — and nowhere in the messages, so it cannot
    # accumulate in the history built from the raw content
    assert log in system_msg
    assert log not in prompt[-1]["content"]
    assert prompt[-1]["content"] == "add a retry step"
    assert prompt[0]["content"] == "hello"


def test_build_prompt_without_attachments_is_unchanged():
    """Production callers send no attachments; their prompt must not move."""
    with_none, _ = build_prompt(content="add a step", existing_yaml="name: wf", history=[])
    with_empty, _ = build_prompt(
        content="add a step", existing_yaml="name: wf", history=[], attachments=[],
    )

    assert with_none == with_empty
    assert "attachment" not in with_none


def test_build_prompt_readonly_mode():
    system_msg, prompt = build_prompt(
        content="What does this workflow do?",
        existing_yaml="name: readonly-workflow",
        read_only=True,
        history=[],
    )

    assert "Read-only Mode" in system_msg
    assert "triple-backticked YAML code blocks" in system_msg
    assert "user is viewing this read-only YAML" in system_msg
    assert "name: readonly-workflow" in system_msg

    assert prompt[-1]["content"] == "What does this workflow do?"
