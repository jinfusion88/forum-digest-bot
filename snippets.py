from dataclasses import dataclass
from datetime import datetime


@dataclass
class FakeMessage:
    id: int
    content: str
    author_id: int
    reaction_count: int
    created_at: datetime
    is_attachment_or_embed_only: bool


def _most_reacted(messages: list[FakeMessage]) -> FakeMessage | None:
    candidates = [m for m in messages if not m.is_attachment_or_embed_only and m.reaction_count > 0]
    if not candidates:
        return None
    return max(candidates, key=lambda m: m.reaction_count)


def _most_recent_substantive(messages: list[FakeMessage]) -> FakeMessage | None:
    candidates = [m for m in messages if not m.is_attachment_or_embed_only]
    if not candidates:
        return None
    return max(candidates, key=lambda m: m.created_at)


GENERIC_FALLBACK = "Join the conversation and see what it's about."


def _generic_fallback(messages: list[FakeMessage]) -> FakeMessage | None:
    return FakeMessage(
        id=0, content=GENERIC_FALLBACK, author_id=0, reaction_count=0,
        created_at=datetime.min, is_attachment_or_embed_only=False,
    )


STRATEGIES = [_most_reacted, _most_recent_substantive, _generic_fallback]


def select_snippet(messages: list[FakeMessage], char_budget: int) -> str | None:
    for strategy in STRATEGIES:
        chosen = strategy(messages)
        if chosen is not None:
            return chosen.content[:char_budget]
    return None
