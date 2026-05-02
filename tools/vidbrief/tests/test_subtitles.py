from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from vidbrief.subtitles import choose_subtitle_file, discover_subtitle_files, read_subtitle_text


class SubtitleTests(unittest.TestCase):
    def test_reads_vtt_without_timings_tags_or_duplicate_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample [abc].en.vtt"
            path.write_text(
                """WEBVTT

00:00:00.000 --> 00:00:01.000
<c>Hello</c> &amp; welcome

00:00:01.000 --> 00:00:02.000
<c>Hello</c> &amp; welcome

00:00:02.000 --> 00:00:03.000
Next line
""",
                encoding="utf-8",
            )

            self.assertEqual(read_subtitle_text(path), "Hello & welcome\nNext line")

    def test_reads_json3_segments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample [abc].en.json3"
            path.write_text(
                '{"events":[{"segs":[{"utf8":"Hello"},{"utf8":" world"}]},{"segs":[{"utf8":"Next\\nline"}]}]}',
                encoding="utf-8",
            )

            self.assertEqual(read_subtitle_text(path), "Hello world\nNext line")

    def test_prefers_chinese_vtt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            en = root / "sample [abc].en.vtt"
            zh = root / "sample [abc].zh-Hans.vtt"
            other = root / "other [def].zh-Hans.vtt"
            for path in (en, zh, other):
                path.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nx\n", encoding="utf-8")

            files = discover_subtitle_files(root, "abc")

            self.assertEqual(files, [zh, en])
            self.assertEqual(choose_subtitle_file(files), zh)


if __name__ == "__main__":
    unittest.main()
