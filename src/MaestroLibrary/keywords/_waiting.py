from datetime import timedelta

from robotlibcore import keyword

from ..locators import to_selector
from ._element import contains


class WaitingKeywords:
    """AppiumLibrary's Wait Until keywords, run by Maestro's extendedWaitUntil.

    `timeout` defaults to the library timeout. `error` replaces the default failure message.
    """

    def __init__(self, lib):
        self.lib = lib

    @keyword
    def wait_until_element_is_visible(self, locator: str, timeout: timedelta | None = None,
                                      error: str | None = None):
        """Waits until the element matching `locator` is visible."""
        self.lib.wait_until(to_selector(locator), True, timeout,
                            error or f"Element '{locator}' was not visible in {self._t(timeout)}.")

    @keyword
    def wait_until_page_contains(self, text: str, timeout: timedelta | None = None, error: str | None = None):
        """Waits until an element containing `text` is visible."""
        self.lib.wait_until(contains(text), True, timeout,
                            error or f"Text '{text}' did not appear in {self._t(timeout)}.")

    @keyword
    def wait_until_page_does_not_contain(self, text: str, timeout: timedelta | None = None,
                                         error: str | None = None):
        """Waits until no visible element contains `text`."""
        self.lib.wait_until(contains(text), False, timeout,
                            error or f"Text '{text}' did not disappear in {self._t(timeout)}.")

    @keyword
    def wait_until_page_contains_element(self, locator: str, timeout: timedelta | None = None,
                                         error: str | None = None):
        """Waits until the element matching `locator` is visible."""
        self.lib.wait_until(to_selector(locator), True, timeout,
                            error or f"Element '{locator}' did not appear in {self._t(timeout)}.")

    @keyword
    def wait_until_page_does_not_contain_element(self, locator: str, timeout: timedelta | None = None,
                                                 error: str | None = None):
        """Waits until the element matching `locator` is gone."""
        self.lib.wait_until(to_selector(locator), False, timeout,
                            error or f"Element '{locator}' did not disappear in {self._t(timeout)}.")

    @keyword
    def wait_for_animation_to_end(self, timeout: timedelta | None = None):
        """Waits until the screen stops changing, or `timeout` passes. Maestro-only."""
        self.lib.run_commands({"waitForAnimationToEnd": {"timeout": self.lib.timeout_ms(timeout)}})

    def _t(self, timeout):
        return f"{self.lib.timeout_ms(timeout) / 1000:g} seconds"
