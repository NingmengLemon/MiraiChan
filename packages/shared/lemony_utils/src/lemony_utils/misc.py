def to_ordinal(n: int) -> str:
    if not isinstance(n, int) or n <= 0:
        raise ValueError("positive integer required")

    # 特别处理 11 ~ 13
    if 11 <= (n % 100) <= 13:
        suffix = "th"
    else:
        last_digit = n % 10
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(last_digit, "th")
    return f"{n}{suffix}"
