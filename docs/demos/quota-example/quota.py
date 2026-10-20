import math


def remaining_percent(usage_level):
    # Only JSON-decoded int/float are accepted; bool, str, Decimal etc. are unknown.
    if type(usage_level) is int:
        # Ints are always finite; math.isfinite would raise OverflowError on huge ints.
        valid = 0 <= usage_level <= 1
    elif type(usage_level) is float:
        valid = math.isfinite(usage_level) and 0 <= usage_level <= 1
    else:
        valid = False
    if not valid:
        return None
    return round((1 - usage_level) * 100.0, 1)
