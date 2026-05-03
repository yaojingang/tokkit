from __future__ import annotations

import unittest

from vidbrief.downloader import DEFAULT_SUBTITLE_LANGS, DEFAULT_VIDEO_FORMAT, parse_cookies_from_browser
from vidbrief.utils import format_seconds, safe_stem


class UtilsAndDownloaderTests(unittest.TestCase):
    def test_safe_stem_removes_path_separators_and_appends_id(self) -> None:
        self.assertEqual(safe_stem("a/b:c", "xyz"), "a b c [xyz]")

    def test_format_seconds(self) -> None:
        self.assertEqual(format_seconds(65), "1:05")
        self.assertEqual(format_seconds(3661), "1:01:01")

    def test_parse_cookies_from_browser(self) -> None:
        self.assertEqual(parse_cookies_from_browser("chrome"), ("chrome", None, None, None))
        self.assertEqual(
            parse_cookies_from_browser("firefox:default-release::container"),
            ("firefox", "default-release", None, "container"),
        )
        self.assertEqual(parse_cookies_from_browser("chrome+keychain:Profile 1"), ("chrome", "Profile 1", "keychain", None))

    def test_default_subtitle_languages_are_exact(self) -> None:
        self.assertIn("zh-Hans", DEFAULT_SUBTITLE_LANGS)
        self.assertIn("en-US", DEFAULT_SUBTITLE_LANGS)
        self.assertTrue(all("*" not in language and "." not in language for language in DEFAULT_SUBTITLE_LANGS))

    def test_default_video_format_is_capped(self) -> None:
        self.assertIn("height<=720", DEFAULT_VIDEO_FORMAT)


if __name__ == "__main__":
    unittest.main()
