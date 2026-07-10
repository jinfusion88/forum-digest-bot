from datetime import datetime, timedelta, timezone
from snippets import FakeMessage, select_snippet, GENERIC_FALLBACK

def msg(id, content, reactions=0, minutes_ago=0, attachment_only=False):
    now = datetime(2026, 7, 9, 12, 0, tzinfo=timezone.utc)
    return FakeMessage(
        id=id, content=content, author_id=1, reaction_count=reactions,
        created_at=now - timedelta(minutes=minutes_ago),
        is_attachment_or_embed_only=attachment_only,
    )

def test_picks_most_reacted_message():
    messages = [
        msg(1, "low reactions", reactions=1, minutes_ago=10),
        msg(2, "the popular one", reactions=9, minutes_ago=5),
        msg(3, "medium", reactions=4, minutes_ago=1),
    ]
    assert select_snippet(messages, char_budget=150) == "the popular one"

def test_falls_back_to_most_recent_substantive_when_no_reactions():
    messages = [
        msg(1, "older message", reactions=0, minutes_ago=10),
        msg(2, "newest message", reactions=0, minutes_ago=1),
    ]
    assert select_snippet(messages, char_budget=150) == "newest message"

def test_skips_attachment_only_messages_in_recency_fallback():
    messages = [
        msg(1, "", reactions=0, minutes_ago=1, attachment_only=True),
        msg(2, "real content here", reactions=0, minutes_ago=5),
    ]
    assert select_snippet(messages, char_budget=150) == "real content here"

def test_skips_attachment_only_messages_even_if_most_reacted():
    messages = [
        msg(1, "", reactions=9, minutes_ago=1, attachment_only=True),
        msg(2, "substantive text", reactions=2, minutes_ago=5),
    ]
    assert select_snippet(messages, char_budget=150) == "substantive text"

def test_truncates_to_char_budget():
    long_text = "x" * 300
    messages = [msg(1, long_text, reactions=5, minutes_ago=1)]
    result = select_snippet(messages, char_budget=150)
    assert len(result) == 150

def test_falls_back_to_generic_string_when_nothing_qualifies():
    messages = [msg(1, "", reactions=5, minutes_ago=1, attachment_only=True)]
    assert select_snippet(messages, char_budget=150) == GENERIC_FALLBACK

def test_empty_message_list_returns_generic_fallback():
    assert select_snippet([], char_budget=150) == GENERIC_FALLBACK
