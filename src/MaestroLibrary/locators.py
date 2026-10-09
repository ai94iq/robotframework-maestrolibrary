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
