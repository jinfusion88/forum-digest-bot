import pytest
from config import Config, load_config

def test_load_config_applies_defaults_for_missing_keys(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("min_messages: 8\n")
    cfg = load_config(str(config_path))
    assert cfg.min_messages == 8
    assert cfg.min_participants == 3
    assert cfg.cooldown_days == 7
    assert cfg.digest_days == ["monday", "friday"]
    assert cfg.digest_time == "16:00"
    assert cfg.timezone == "America/Chicago"
    assert cfg.digest_title == "Featured Discussions This Week"
    assert cfg.new_thread_delay_minutes == 60
    assert cfg.new_thread_staleness_cap_hours == 24
    assert cfg.backfill_message_cap == 200
    assert cfg.snippet_char_budget == 150
    assert cfg.max_featured_threads == 5
    assert cfg.new_thread_boost_messages == 2

def test_load_config_missing_file_uses_all_defaults(tmp_path):
    cfg = load_config(str(tmp_path / "does_not_exist.yaml"))
    assert cfg.min_messages == 5
