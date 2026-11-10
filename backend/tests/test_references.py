from __future__ import annotations

import json

from app.models.review import MessageRole, ReviewThread, ThreadMessage
from app.services.references import find_references, format_references_block
from tests.fixtures import as_result, provision
from tests.test_review_pipeline import FINDINGS, configure


def make_thread(path: str, line: int, finding: str, conclusion: str | None = None) -> ReviewThread:
    thread = ReviewThread(file_path=path, line_number=line, diff_hunk="+ changed")
    thread.messages = [ThreadMessage(role=MessageRole.ASSISTANT, content=finding)]
    if conclusion:
        thread.messages.append(ThreadMessage(role=MessageRole.USER, content="why?"))
        thread.messages.append(ThreadMessage(role=MessageRole.ASSISTANT, content=conclusion))
    return thread


def test_resolves_ordinals_in_mention_order():
    threads = [
        make_thread("a.py", 10, "first"),
        make_thread("b.py", 20, "second"),
        make_thread("c.py", 30, "third"),
    ]
    refs = find_references("same root cause as #3 and #1, also #3 again", threads)
    assert [ref.ordinal for ref in refs] == [3, 1]
    assert refs[0].file_path == "c.py" and refs[0].line_number == 30


def test_ignores_out_of_range_and_non_references():
    threads = [make_thread("a.py", 10, "first")]
    assert find_references("#2 #0 #99", threads) == []
    assert find_references("#abc &#39; #", threads) == []
    assert [ref.ordinal for ref in find_references("#1", threads)] == [1]


def test_reference_block_carries_the_conclusion():
    threads = [make_thread("a.py", 10, "**High** — original problem", "Now guarded.")]
    refs = find_references("like #1", threads)
    block = format_references_block(refs)
    assert "Referenced threads" in block
    assert "#1" in block and "a.py:10" in block
    assert "**High** — original problem" in block
    assert "Latest conclusion: Now guarded." in block


def test_block_is_empty_without_references():
    assert format_references_block([]) == ""


def test_discussion_with_a_reference_reaches_the_model(client, monkeypatch):
    from tests.conftest import start_review

    configure(monkeypatch, json.dumps(FINDINGS))
    provision(client)
    review = start_review(client, "https://github.com/octo/example/pull/123", "ollama-local:llama3")

    captured: list[str] = []

    async def capture(settings_row, model, system_prompt, user_prompt, json_mode=False, **kwargs):
        captured.append(user_prompt)
        return "Same guard, different call site — fix both."

    monkeypatch.setattr("app.services.llm_service.generate", as_result(capture))

    response = client.post(
        f"/api/reviews/{review['id']}/discuss",
        json={
            "threads": [
                {
                    "thread_id": review["threads"][1]["id"],
                    "message": "This is the same root cause as #1 and #7",
                }
            ]
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["results"][0]["references"] == [1]
    # The last call is the verdict pass; the discussion prompt is the one that carries references.
    discussion_prompt = next(prompt for prompt in captured if "Conversation so far" in prompt)
    assert "Referenced threads" in discussion_prompt
    assert "#1" in discussion_prompt
    assert "src/services/auth.py:11" in discussion_prompt
    # #7 does not exist in this review, so it gets no reference heading (it still appears in
    # the reviewer's own message, which is echoed back as part of the transcript).
    assert "### #7" not in discussion_prompt
