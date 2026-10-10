"""AppiumLibrary-style `strategy=value` locators, translated to Maestro selectors."""

import re

UNSUPPORTED = ("xpath", "class", "android", "ios", "predicate", "chain", "css", "name", "identifier")


def to_selector(locator):
    """Returns the Maestro selector dict for `locator`.

    `text=` and `id=` values are literal, matching the whole text or id, as in AppiumLibrary.
    `regex=` and `id_regex=` pass a Maestro regular expression through unchanged. A value with
    no strategy is treated as text, because Flutter widgets have text far more often than ids.
    """
    strategy, value = _split(locator)
    if strategy in ("text", "accessibility_id"):
        return {"text": re.escape(value)}
    if strategy == "regex":
        return {"text": value}
    if strategy == "id":
        return {"id": re.escape(value)}
    if strategy == "id_regex":
        return {"id": value}
    if strategy == "point":
        return {"point": value.replace(" ", "")}
    if strategy in UNSUPPORTED:
        raise ValueError(
            f"Locator strategy '{strategy}' is not supported by Maestro. "
            "Use id=, text=, accessibility_id=, regex=, id_regex= or point=."
        )
    raise ValueError(f"Unknown locator strategy '{strategy}' in '{locator}'.")


def _split(locator):
    locator = str(locator)
    if locator.startswith("//") or locator.startswith("(//"):
        return "xpath", locator
    head, sep, tail = locator.partition("=")
    if sep and re.fullmatch(r"[a-z_]+", head.strip()):
        return head.strip(), tail.strip()
    return "text", locator


def matches(element, selector):
    """True if an `inspect_screen` element matches a Maestro selector made by `to_selector`."""
    if "id" in selector:
        return bool(re.fullmatch(selector["id"], element.get("rid", ""), re.S))
    if "text" in selector:
        return any(
            re.fullmatch(selector["text"], element.get(key, ""), re.S) for key in ("txt", "a11y", "hint")
        )
    return False


def walk(elements):
    """Yields every element of an `inspect_screen` tree, depth first."""
    for element in elements:
        yield element
        yield from walk(element.get("c", []))


LOCATABLE = ("rid", "txt", "a11y", "hint")


def parse_bounds(b):
    """Returns (x1, y1, x2, y2) from an inspect_screen bounds string such as ``[0,0][1080,2400]``."""
    found = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", b or "")
    return tuple(int(n) for n in found.groups()) if found else None


def element_at(elements, x, y):
    """The smallest element at device point (x, y) with something a locator can use, from a flat list."""
    hits = []
    for element in elements:
        box = parse_bounds(element.get("b"))
        if box and box[0] <= x < box[2] and box[1] <= y < box[3] and any(element.get(k) for k in LOCATABLE):
            hits.append(((box[2] - box[0]) * (box[3] - box[1]), element))
    return min(hits, key=lambda hit: hit[0])[1] if hits else None


def locator_candidates(element, elements):
    """[(locator, match count)]: id= first, then text= for text, content-desc and hint."""
    candidates = ([f"id={element['rid']}"] if element.get("rid") else []) + \
        [f"text={element[k]}" for k in ("txt", "a11y", "hint") if element.get(k)]
    return [(c, sum(matches(e, to_selector(c)) for e in elements)) for c in dict.fromkeys(candidates)]


def best_locator(element, elements):
    """The first candidate locator that matches exactly one element, or None."""
    return next((c for c, count in locator_candidates(element, elements) if count == 1), None)
