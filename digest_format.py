from dataclasses import dataclass, field


@dataclass
class ThreadRenderData:
    thread_id: int
    title: str
    jump_url: str
    starter_is_url: bool
    starter_text: str
    reply_count: int
    participant_count: int


@dataclass
class DigestMessage:
    content: str
    mention_role_ids: list[int] = field(default_factory=list)


DEFAULT_STATS_EMOJIS = ("🔥", "🌩️", "⚡")  # (low, mid, high) activity tiers


def _stats_emoji(reply_count: int, mid_threshold: int, high_threshold: int,
                 emojis: tuple[str, str, str]) -> str:
    low, mid, high = emojis
    if reply_count >= high_threshold:
        return high
    if reply_count >= mid_threshold:
        return mid
    return low


def _render_thread_block(thread: ThreadRenderData, mid_threshold: int,
                         high_threshold: int, emojis: tuple[str, str, str]) -> str:
    lines = [f"**{thread.title}**"]
    if thread.starter_is_url:
        lines.append(thread.starter_text)
    else:
        lines.append(f"> {thread.starter_text}")
    emoji = _stats_emoji(thread.reply_count, mid_threshold, high_threshold, emojis)
    lines.append(
        f"{emoji} **{thread.reply_count} replies** from "
        f"**{thread.participant_count} members** this week!"
    )
    # Bare thread link (no <> suppression): discord.com/channels links don't
    # embed-unfurl; they render as a clickable inline thread chip.
    lines.append(f"Go check out what's brewing → {thread.jump_url}")
    return "\n".join(lines)


def format_digest(
    threads: list[ThreadRenderData],
    role_id: int | None,
    title: str,
    char_limit: int = 2000,
    stats_mid_threshold: int = 15,
    stats_high_threshold: int = 25,
    stats_emojis: tuple[str, str, str] = DEFAULT_STATS_EMOJIS,
) -> list[DigestMessage]:
    mention = f"<@&{role_id}> " if role_id is not None else ""
    header = f"{mention}Here are the {title}!"
    blocks = [
        _render_thread_block(t, stats_mid_threshold, stats_high_threshold, stats_emojis)
        for t in threads
    ]

    messages: list[DigestMessage] = []
    current_lines = [header]
    current_role_ids = [role_id] if role_id is not None else []
    current_len = len(header)

    for block in blocks:
        addition_len = len(block) + 2  # blank line separator

        # Flush only once the current message already holds content beyond its
        # anchor (the header for the first message, nothing for later ones) —
        # never emit an anchor-only/empty message.
        has_content_beyond_anchor = len(current_lines) > (1 if not messages else 0)
        if current_len + addition_len > char_limit and has_content_beyond_anchor:
            messages.append(DigestMessage("\n\n".join(current_lines), current_role_ids))
            current_lines = []
            current_role_ids = []
            current_len = 0
            addition_len = len(block)  # fresh message: no anchor, no separator yet

        if current_len + addition_len > char_limit:
            # Even alone (with whatever anchor is already committed), this block
            # exceeds char_limit on its own — truncate so no message ever exceeds it.
            separator_len = addition_len - len(block)
            available = max(char_limit - current_len - separator_len, 0)
            block = block[:available]
            addition_len = len(block) + separator_len

        current_lines.append(block)
        current_len += addition_len

    if current_lines:
        messages.append(DigestMessage("\n\n".join(current_lines), current_role_ids))

    return messages
