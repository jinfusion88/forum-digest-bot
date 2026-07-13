from dataclasses import dataclass, field
import os
import yaml


@dataclass
class Config:
    min_messages: int = 5
    min_participants: int = 3
    cooldown_days: int = 7
    new_thread_boost_messages: int = 2
    digest_days: list[str] = field(default_factory=lambda: ["monday", "friday"])
    digest_time: str = "16:00"
    timezone: str = "America/Chicago"
    digest_title: str = "Featured Discussions This Week"
    new_thread_delay_minutes: int = 60
    new_thread_staleness_cap_hours: int = 24
    backfill_message_cap: int = 200
    snippet_char_budget: int = 150
    max_featured_threads: int = 5
    stats_tier_mid_replies: int = 15
    stats_tier_high_replies: int = 25
    stats_emoji_low: str = "🔥"
    stats_emoji_mid: str = "🌩️"
    stats_emoji_high: str = "⚡"


def load_config(path: str) -> Config:
    if not os.path.exists(path):
        return Config()
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    defaults = Config()
    kwargs = {}
    for key in defaults.__dataclass_fields__:
        if key in raw:
            kwargs[key] = raw[key]
    return Config(**kwargs)
