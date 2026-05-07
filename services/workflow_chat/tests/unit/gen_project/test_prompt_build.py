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
