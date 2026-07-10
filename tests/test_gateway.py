# tests/test_gateway.py
from datetime import datetime, timezone
from gateway import RealDiscordGateway

class FakeReaction:
    def __init__(self, count):
        self.count = count

class FakeAuthor:
    def __init__(self, id):
        self.id = id

class FakeDiscordMessage:
    def __init__(self, id, content, author_id, reactions=None, created_at=None, attachments=None, embeds=None):
        self.id = id
        self.content = content
        self.author = FakeAuthor(author_id)
        self.reactions = reactions or []
        self.created_at = created_at or datetime.now(timezone.utc)
        self.attachments = attachments or []
        self.embeds = embeds or []

def test_to_fake_message_sums_reaction_counts():
    msg = FakeDiscordMessage(1, "hello", 100, reactions=[FakeReaction(3), FakeReaction(2)])
    result = RealDiscordGateway._to_fake_message(msg)
    assert result.reaction_count == 5
    assert result.content == "hello"
    assert result.author_id == 100
    assert result.is_attachment_or_embed_only is False

def test_to_fake_message_flags_attachment_only_when_content_empty():
    msg = FakeDiscordMessage(1, "", 100, attachments=["file.png"])
    result = RealDiscordGateway._to_fake_message(msg)
    assert result.is_attachment_or_embed_only is True

def test_to_backfill_message_sums_reactions():
    msg = FakeDiscordMessage(1, "hello", 100, reactions=[FakeReaction(4)])
    result = RealDiscordGateway._to_backfill_message(msg)
    assert result.author_id == 100
    assert result.reaction_count == 4

def test_starter_message_url_detection_bare_url():
    assert RealDiscordGateway._is_bare_url("https://example.com/article") is True
    assert RealDiscordGateway._is_bare_url("check this out: https://example.com") is False
    assert RealDiscordGateway._is_bare_url("just some text") is False

def test_build_digest_allowed_mentions_restricts_to_role_only():
    mentions = RealDiscordGateway._build_digest_allowed_mentions(mention_role_ids=[555])
    assert mentions.everyone is False
    assert mentions.users is False
    assert [r.id for r in mentions.roles] == [555]

def test_build_digest_allowed_mentions_empty_role_list_still_suppresses_everyone_and_users():
    mentions = RealDiscordGateway._build_digest_allowed_mentions(mention_role_ids=[])
    assert mentions.everyone is False
    assert mentions.users is False
    assert mentions.roles == []
