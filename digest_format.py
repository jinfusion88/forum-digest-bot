from dataclasses import dataclass, field


@dataclass
class ThreadRenderData:
    thread_id: int
    title: str
    jump_url: str
    starter_is_url: bool
    starter_text: str
    snippet: str | None
    reply_count: int
    participant_count: int


@dataclass
class DigestMessage:
    content: str
    mention_role_ids: list[int] = field(default_factory=list)


def _render_thread_block(thread: ThreadRenderData) -> str:
    lines = [f"**{thread.title}**", f"<{thread.jump_url}>"]
    if thread.starter_is_url:
        lines.append(thread.starter_text)
    else:
        lines.append(f"> {thread.starter_text}")
    if thread.snippet:
        lines.append(f"> {thread.snippet}")
    lines.append(f"_{thread.reply_count} replies from {thread.participant_count} members this week_")
    return "\n".join(lines)


def format_digest(
    threads: list[ThreadRenderData],
    role_id: int,
    title: str,
    char_limit: int = 2000,
) -> list[DigestMessage]:
    header = f"<@&{role_id}> **{title}**"
    blocks = [_render_thread_block(t) for t in threads]

    messages: list[DigestMessage] = []
    current_lines = [header]
    current_role_ids = [role_id]
    current_len = len(header)

    for block in blocks:
        addition_len = len(block) + 2  # blank line separator
        if current_len + addition_len > char_limit and len(current_lines) > (1 if not messages else 0):
            messages.append(DigestMessage("\n\n".join(current_lines), current_role_ids))
            current_lines = []
            current_role_ids = []
            current_len = 0
        current_lines.append(block)
        current_len += addition_len

    if current_lines:
        messages.append(DigestMessage("\n\n".join(current_lines), current_role_ids))

    return messages
