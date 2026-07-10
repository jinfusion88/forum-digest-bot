from digest_format import ThreadRenderData, format_digest

def make_thread(thread_id, starter_is_url=False, starter_text="Some excerpt", snippet="A snippet"):
    return ThreadRenderData(
        thread_id=thread_id,
        title=f"Thread {thread_id}",
        jump_url=f"https://discord.com/channels/1/2/{thread_id}",
        starter_is_url=starter_is_url,
        starter_text=starter_text,
        snippet=snippet,
        reply_count=12,
        participant_count=7,
    )

def test_role_ping_is_in_content_of_first_message():
    threads = [make_thread(1)]
    result = format_digest(threads, role_id=555, title="Featured Discussions This Week")
    assert "<@&555>" in result[0].content
    assert result[0].mention_role_ids == [555]

def test_jump_link_is_wrapped_to_suppress_unfurl():
    threads = [make_thread(1)]
    result = format_digest(threads, role_id=555, title="Featured")
    assert "<https://discord.com/channels/1/2/1>" in result[0].content

def test_bare_starter_url_is_not_wrapped_so_it_unfurls():
    threads = [make_thread(1, starter_is_url=True, starter_text="https://example.com/article")]
    result = format_digest(threads, role_id=555, title="Featured")
    assert "\nhttps://example.com/article\n" in result[0].content or \
        result[0].content.endswith("https://example.com/article")
    assert "<https://example.com/article>" not in result[0].content

def test_stats_line_is_invitational_not_competitive():
    threads = [make_thread(1)]
    result = format_digest(threads, role_id=555, title="Featured")
    assert "12 replies from 7 members" in result[0].content
    assert "winner" not in result[0].content.lower()
    assert "#1" not in result[0].content

def test_no_ordinal_numbering_in_thread_blocks():
    threads = [make_thread(1), make_thread(2)]
    result = format_digest(threads, role_id=555, title="Featured")
    full_text = "\n".join(m.content for m in result)
    for line in full_text.split("\n"):
        assert not line.strip().startswith(("1.", "2.", "#1", "#2"))

def test_splits_into_multiple_messages_when_over_char_limit():
    threads = [make_thread(i, snippet="x" * 140) for i in range(1, 6)]
    result = format_digest(threads, role_id=555, title="Featured", char_limit=400)
    assert len(result) > 1
    assert result[0].mention_role_ids == [555]
    for later in result[1:]:
        assert later.mention_role_ids == []
    for m in result:
        assert len(m.content) <= 400

def test_single_message_when_under_char_limit():
    threads = [make_thread(1)]
    result = format_digest(threads, role_id=555, title="Featured", char_limit=2000)
    assert len(result) == 1

def test_oversized_single_block_is_truncated_not_left_over_limit():
    huge_thread = make_thread(1, snippet="x" * 3000)
    result = format_digest([huge_thread], role_id=555, title="Featured", char_limit=400)
    assert len(result) == 1
    assert len(result[0].content) <= 400

def test_no_role_configured_omits_ping_and_mentions():
    threads = [make_thread(1)]
    result = format_digest(threads, role_id=None, title="Featured")
    assert "<@&" not in result[0].content
    assert result[0].mention_role_ids == []
