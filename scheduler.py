from apscheduler.triggers.cron import CronTrigger

_DAY_ABBREVIATIONS = {
    "monday": "mon", "tuesday": "tue", "wednesday": "wed", "thursday": "thu",
    "friday": "fri", "saturday": "sat", "sunday": "sun",
}


def build_digest_cron_trigger(days: list[str], time_str: str, timezone_name: str) -> CronTrigger:
    hour, minute = (int(part) for part in time_str.split(":"))
    day_of_week = ",".join(_DAY_ABBREVIATIONS[d.lower()] for d in days)
    return CronTrigger(day_of_week=day_of_week, hour=hour, minute=minute, timezone=timezone_name)
