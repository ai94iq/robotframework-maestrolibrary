from robotlibcore import keyword


class RunOnFailureKeywords:
    def __init__(self, lib):
        self.lib = lib

    @keyword
    def register_keyword_to_run_on_failure(self, keyword: str) -> str:
        """Sets the keyword to run when any MaestroLibrary keyword fails and returns the previous one.

        Use ``Nothing`` to turn it off. The default is `Capture Page Screenshot`.
        """
        old = self.lib.run_on_failure_keyword or "Nothing"
        self.lib.run_on_failure_keyword = None if keyword.upper() in ("NOTHING", "NONE", "") else keyword
        return old
