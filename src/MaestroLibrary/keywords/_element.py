import json
import re
from datetime import timedelta
from typing import Literal

from robot.api import logger
from robotlibcore import keyword

from ..locators import to_selector

# inspect_screen abbreviates attribute names and omits attributes equal to these defaults.
ABBREVIATIONS = {"bounds": "b", "text": "txt", "resource-id": "rid", "content-desc": "a11y",
                 "hintText": "hint", "hint": "hint", "class": "cls", "scrollable": "scroll"}
DEFAULTS = {"enabled": True, "clickable": False, "focused": False, "selected": False, "checked": False,
            "scroll": False, "txt": "", "hint": "", "rid": "", "a11y": "", "cls": ""}
State = Literal["visible", "not visible", "enabled", "disabled"]


def contains(text):
    return {"text": f".*{re.escape(text)}.*"}


class ElementKeywords:
    def __init__(self, lib):
        self.lib = lib

    @keyword
    def click_element(self, locator: str):
        """Taps the element identified by `locator`, waiting for it to appear first."""
        self.lib.run_commands({"tapOn": to_selector(locator)})

    @keyword
    def click_text(self, text: str, exact_match: bool = False):
        """Taps the element whose text is `text`, or contains it unless `exact_match` is true."""
        self.lib.run_commands({"tapOn": {"text": re.escape(text)} if exact_match else contains(text)})

    @keyword
    def click_alert_button(self, button_name: str):
        """Taps the button of a system alert or dialog whose text is exactly `button_name`.

        AppiumLibrary's iOS keyword; here it works on both platforms, as an exact-text tap.
        iOS: WIP, needs testing on an iOS simulator.

        | `Click Alert Button` | Allow |
        """
        self.click_text(button_name, exact_match=True)

    @keyword
    def input_text(self, locator: str, text: str):
        """Taps the element identified by `locator` and types `text` into it."""
        self.lib.run_commands({"tapOn": to_selector(locator)}, {"inputText": text})

    @keyword
    def input_password(self, locator: str, text: str):
        """Like `Input Text`, but the text is never logged."""
        logger.info(f"Typing password into '{locator}'.")
        self.lib.run_commands({"tapOn": to_selector(locator)}, {"inputText": text}, log=False)

    @keyword
    def input_text_into_current_element(self, text: str):
        """Types `text` into the focused element."""
        self.lib.run_commands({"inputText": text})

    @keyword
    def clear_text(self, locator: str):
        """Taps the text field identified by `locator` and erases its contents."""
        found = self.lib.find(to_selector(locator))
        length = len(found[0].get("txt", "")) if found else 0
        self.lib.run_commands({"tapOn": to_selector(locator)}, {"eraseText": max(length, 50)})

    @keyword
    def hide_keyboard(self, key_name: str | None = None):
        """Hides the software keyboard if one is shown.

        `key_name`, as in AppiumLibrary, is iOS only: there the keyboard key with that text (for
        example ``Done``) is tapped instead of Maestro's swipe. On Android it is ignored.
        iOS: WIP, needs testing on an iOS simulator.

        On Android, Maestro's hideKeyboard always presses Back, which leaves the screen (or
        the app) when no keyboard is up, for example after a PIN field closed it by itself.
        This keyword presses only while `Is Keyboard Shown` is true.
        """
        if self.lib.device_id() and self.lib.platform == "android" and not self.is_keyboard_shown():
            logger.info("No keyboard is shown; nothing to hide.")
            return
        if key_name and self.lib.platform != "android":
            self.click_text(key_name, exact_match=True)
            return
        self.lib.run_commands("hideKeyboard")

    @keyword
    def is_keyboard_shown(self) -> bool:
        """Returns whether the software keyboard is shown. Android only (``dumpsys input_method``).

        Without adb, it assumes a keyboard is shown, so `Hide Keyboard` behaves like Maestro's.
        """
        self.lib.device_id()
        if self.lib.platform != "android":
            raise NotImplementedError("Is Keyboard Shown supports Android only.")
        state = self.lib.adb_shell("dumpsys", "input_method", purpose="checking the keyboard")
        return True if state is None else "mInputShown=true" in state

    @keyword
    def page_should_contain_text(self, text: str, loglevel: str = "INFO"):
        """Fails unless some element on the current screen contains `text`."""
        self._check(contains(text), True, f"Page should have contained text '{text}' but did not.", loglevel)

    @keyword
    def page_should_not_contain_text(self, text: str, loglevel: str = "INFO"):
        """Fails if some element on the current screen contains `text`."""
        self._check(contains(text), False, f"Page should not have contained text '{text}'.", loglevel)

    @keyword
    def page_should_contain_element(self, locator: str, loglevel: str = "INFO"):
        """Fails unless the current screen has an element matching `locator`."""
        self._check(to_selector(locator), True, f"Page should have contained element '{locator}' but did not.",
                    loglevel)

    @keyword
    def page_should_not_contain_element(self, locator: str, loglevel: str = "INFO"):
        """Fails if the current screen has an element matching `locator`."""
        self._check(to_selector(locator), False, f"Page should not have contained element '{locator}'.", loglevel)

    @keyword
    def element_should_be_visible(self, locator: str, loglevel: str = "INFO"):
        """Fails unless an element matching `locator` is on the current screen."""
        self._check(to_selector(locator), True, f"Element '{locator}' should be visible but did not.", loglevel)

    @keyword
    def text_should_be_visible(self, text: str, exact_match: bool = False, loglevel: str = "INFO"):
        """Fails unless an element with text `text` (or containing it) is on the current screen."""
        selector = {"text": re.escape(text)} if exact_match else contains(text)
        self._check(selector, True, f"Text '{text}' should be visible but did not.", loglevel)

    @keyword
    def element_should_be_enabled(self, locator: str, loglevel: str = "INFO"):
        """Fails unless the element matching `locator` is enabled."""
        if not self._attr(self._first(locator, loglevel), "enabled"):
            raise AssertionError(f"Element '{locator}' should be enabled but did not.")

    @keyword
    def element_should_be_disabled(self, locator: str, loglevel: str = "INFO"):
        """Fails unless the element matching `locator` is disabled."""
        if self._attr(self._first(locator, loglevel), "enabled"):
            raise AssertionError(f"Element '{locator}' should be disabled but did not.")

    @keyword
    def element_text_should_be(self, locator: str, expected: str, message: str = ""):
        """Fails unless the text of the element matching `locator` is exactly `expected`."""
        actual = self.get_text(locator)
        if actual != expected:
            raise AssertionError(message or f"Element '{locator}' text should have been '{expected}' but was '{actual}'.")

    @keyword
    def element_should_contain_text(self, locator: str, expected: str, message: str = ""):
        """Fails unless the text of the element matching `locator` contains `expected`."""
        actual = self.get_text(locator)
        if expected not in actual:
            raise AssertionError(message or f"Element '{locator}' should have contained text '{expected}' but its text was '{actual}'.")

    @keyword
    def element_should_not_contain_text(self, locator: str, expected: str, message: str = ""):
        """Fails if the text of the element matching `locator` contains `expected`."""
        actual = self.get_text(locator)
        if expected in actual:
            raise AssertionError(message or f"Element '{locator}' should not contain text '{expected}' but it did.")

    @keyword
    def get_text(self, locator: str, first_only: bool = True) -> str | list[str]:
        """Returns the text of the element matching `locator` (its content-desc if it has no text).

        With `first_only=False`, returns a list with the text of every matching element.
        """
        found = self.lib.find(to_selector(locator))
        if not found:
            raise AssertionError(f"Element '{locator}' did not match any elements.")
        texts = [e.get("txt") or e.get("a11y", "") for e in found]
        return texts[0] if first_only else texts

    @keyword
    def get_element_attribute(self, locator: str, attribute: str):
        """Returns `attribute` of the element matching `locator`.

        Attributes: text, resource-id, content-desc, hintText, class, bounds, enabled,
        clickable, focused, selected, checked, scrollable.
        """
        return self._attr(self._first(locator), ABBREVIATIONS.get(attribute, attribute))

    @keyword
    def scroll_element_into_view(self, locator: str):
        """Scrolls down until the element matching `locator` is visible."""
        self.lib.run_commands({"scrollUntilVisible": {"element": to_selector(locator), "direction": "DOWN"}})

    @keyword
    def expect_element(self, locator: str, state: State, timeout: timedelta | None = None,
                       retry_interval: timedelta | None = None, message: str | None = None,
                       loglevel: str | None = "INFO"):
        """Waits until the element matching `locator` is in `state`: visible, not visible, enabled or disabled.

        `timeout` defaults to the library timeout. Maestro polls on its own, so
        `retry_interval` is accepted for AppiumLibrary compatibility and ignored, as is
        `loglevel`: a failure logs the screenshot of `Register Keyword To Run On Failure`.
        """
        self._expect(to_selector(locator), state, timeout, message or f"Element '{locator}' was not {state}.")

    @keyword
    def expect_text(self, text: str, state: State, exact_match: bool = False, timeout: timedelta | None = None,
                    retry_interval: timedelta | None = None, message: str | None = None,
                    loglevel: str | None = "INFO"):
        """Like `Expect Element`, for an element with text `text`, or containing it unless `exact_match` is true."""
        selector = {"text": re.escape(text)} if exact_match else contains(text)
        self._expect(selector, state, timeout, message or f"Text '{text}' was not {state}.")

    def _expect(self, selector, state, timeout, message):
        if state in ("enabled", "disabled"):
            selector = {**selector, "enabled": state == "enabled"}
        self.lib.wait_until(selector, state != "not visible", timeout, message)

    def _check(self, selector, present, message, loglevel):
        elements = self.lib.find(selector)
        if bool(elements) != present:
            self._log_source(loglevel)
            raise AssertionError(message)

    def _first(self, locator, loglevel="INFO"):
        found = self.lib.find(to_selector(locator))
        if not found:
            self._log_source(loglevel)
            raise AssertionError(f"Element '{locator}' did not match any elements.")
        return found[0]

    def _log_source(self, loglevel):
        if loglevel and loglevel.upper() != "NONE":
            logger.write(json.dumps(self.lib.screen(), indent=1), loglevel)

    @staticmethod
    def _attr(element, name):
        return element.get(name, DEFAULTS.get(name))
