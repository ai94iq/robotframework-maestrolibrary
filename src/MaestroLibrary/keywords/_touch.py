import time
from datetime import timedelta

from robotlibcore import keyword

from ..locators import matches, to_selector
from ..mcp import MaestroError


def ms(duration):
    """Milliseconds of a timedelta; an int already is milliseconds (AppiumLibrary's old form)."""
    return duration if isinstance(duration, int) else int(duration.total_seconds() * 1000)


class TouchKeywords:
    def __init__(self, lib):
        self.lib = lib

    @keyword
    def swipe(self, *, start_x: int, start_y: int, end_x: int, end_y: int,
              duration: int | timedelta = timedelta(seconds=1)):
        """Swipes from one screen point to another, in pixels.

        `duration` takes a time (``300ms``, ``1s``); a bare number is milliseconds, as in AppiumLibrary.

        | `Swipe` | start_x=500 | start_y=1500 | end_x=500 | end_y=500 |
        """
        self._swipe(f"{start_x}, {start_y}", f"{end_x}, {end_y}", duration)

    @keyword
    def swipe_by_percent(self, start_x: float, start_y: float, end_x: float, end_y: float,
                         duration: int | timedelta = timedelta(seconds=1)):
        """Swipes from one screen point to another, in percent of the screen size.

        `duration` takes a time (``300ms``, ``1s``); a bare number is milliseconds, as in AppiumLibrary.

        | `Swipe By Percent` | 50 | 80 | 50 | 20 | # scrolls content up |
        """
        self._swipe(f"{start_x:g}%, {start_y:g}%", f"{end_x:g}%, {end_y:g}%", duration)

    @keyword
    def scroll_down(self, locator: str, timeout: timedelta = timedelta(seconds=10),
                    retry_interval: timedelta = timedelta(seconds=1), x: float | None = None):
        """Scrolls down until the element matching `locator` is visible, or fails after `timeout`.

        `x` swipes along that column, in percent of the screen width, instead of the middle: a
        signature pad, map or canvas in the middle would take the swipe as a drawing. With `x`
        the scroll also stops early when the screen no longer changes (the end of the content).

        | `Scroll Down` | id=submit | x=2 |

        `retry_interval` is accepted for AppiumLibrary compatibility and ignored.
        """
        self._scroll(locator, "DOWN", timeout, x)

    @keyword
    def scroll_up(self, locator: str, timeout: timedelta = timedelta(seconds=10),
                  retry_interval: timedelta = timedelta(seconds=1), x: float | None = None):
        """Scrolls up until the element matching `locator` is visible, or fails after `timeout`.

        `x` works as in `Scroll Down`.
        """
        self._scroll(locator, "UP", timeout, x)

    @keyword
    def tap(self, locator: str, count: int = 1):
        """Taps the element matching `locator` `count` times."""
        command = {**to_selector(locator), "repeat": count} if count > 1 else to_selector(locator)
        self.lib.run_commands({"tapOn": command})

    @keyword
    def long_press(self, locator: str):
        """Long-presses the element matching `locator`."""
        self.lib.run_commands({"longPressOn": to_selector(locator)})

    def _swipe(self, start, end, duration):
        self.lib.run_commands({"swipe": {"start": start, "end": end, "duration": ms(duration)}})

    def _scroll(self, locator, direction, timeout, x=None):
        selector = to_selector(locator)
        try:
            if x is None:
                self.lib.run_commands({"scrollUntilVisible": {
                    "element": selector, "direction": direction, "timeout": ms(timeout)}})
                return
            if self._scroll_column(selector, direction, timeout, x):
                return
        except MaestroError:
            pass
        raise AssertionError(f"Element '{locator}' was not found after scrolling "
                             f"{direction.lower()} for {timeout.total_seconds():g} seconds.")

    def _scroll_column(self, selector, direction, timeout, x):
        # 75% to 40%: a swipe long enough to move a page, short of the edges where system
        # gestures and pinned bars sit.
        start, end = (75, 40) if direction == "DOWN" else (40, 75)
        deadline = time.monotonic() + timeout.total_seconds()
        before = None
        while time.monotonic() < deadline:
            screen = self.lib.elements()
            if any(matches(e, selector) for e in screen):
                return True
            if screen == before:
                break
            before = screen
            self._swipe(f"{x:g}%, {start}%", f"{x:g}%, {end}%", timedelta(milliseconds=400))
        return False
