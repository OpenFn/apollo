"""Unit tests for the line numbers shown with the user's code."""

from job_chat import old_prompt, prompt
from util import add_line_numbers

CODE = "get('/a');\nfn(s => s);"


def test_numbers_match_editor_line_breaks() -> None:
    assert add_line_numbers("a\fb\r\nc\n") == "     1\ta\fb\r\n     2\tc\n     3\t"


def test_both_prompt_modes_number_user_code() -> None:
    for module in (prompt, old_prompt):
        blocks = module.generate_system_message(context_dict={"expression": CODE}, search_results=None)
        text = "\n".join(b["text"] for b in blocks)
        assert "     1\tget('/a');\n     2\tfn(s => s);</user_code>" in text
