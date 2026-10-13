from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from support.agents.graph import _cited_sources, context_window, text_of
from support.agents.state import RESET, merge_events


def test_merge_events_appends_and_resets() -> None:
    assert merge_events([{"type": "a"}], [{"type": "b"}]) == [{"type": "a"}, {"type": "b"}]
    assert merge_events([{"type": "a"}], [{"type": RESET}, {"type": "c"}]) == [{"type": "c"}]
    assert merge_events(None, None) == []


def test_context_window_never_starts_mid_tool_exchange() -> None:
    msgs = [
        HumanMessage("q1"),
        AIMessage("", tool_calls=[{"name": "t", "args": {}, "id": "1"}]),
        ToolMessage("r", tool_call_id="1"),
        AIMessage("a1"),
        HumanMessage("q2"),
        AIMessage("a2"),
    ]
    window = context_window(msgs, 4)  # naive slice would start at the ToolMessage
    assert isinstance(window[0], HumanMessage) and window[0].content == "q2"
    assert context_window(msgs, 100) == msgs


def test_text_of_handles_content_blocks() -> None:
    assert text_of(AIMessage([{"type": "text", "text": "Hi "}, {"type": "text", "text": "there"}])) == "Hi there"


def test_cited_sources_prefers_cited_articles() -> None:
    art = [{"source": "a", "title": "A", "url": "u1"}, {"source": "b", "title": "B", "url": "u2"}]
    msgs = [HumanMessage("q"), ToolMessage("..", tool_call_id="1", name="search_help_center", artifact=art)]
    assert [s["source"] for s in _cited_sources(msgs, "See [b].")] == ["b"]
    assert [s["source"] for s in _cited_sources(msgs, "No citation.")] == ["a", "b"]
    assert _cited_sources([HumanMessage("q")], "x") == []
