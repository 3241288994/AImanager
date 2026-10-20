def remaining_percent(usage_level):
    return round((1 - (usage_level or 0)) * 100, 1)
