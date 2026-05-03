from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from memview.cli import (
    GraphicsDevice,
    MemoryCategory,
    MemorySnapshot,
    ProcessMemory,
    SoftwareActivity,
    TUI_VIEWS,
    app_bundle_name_for_software,
    bar,
    build_optimization_plan,
    format_bytes,
    guide_commands,
    collect_snapshot,
    overall_status,
    parse_cli_args,
    parse_darwin_swap,
    parse_darwin_display_devices,
    parse_ioreg_agc_info,
    parse_ioreg_performance_statistics,
    parse_linux_meminfo,
    parse_memory_pressure_free_percent,
    parse_vm_stat,
    print_output,
    quit_command_for_software,
    render_completion_script,
    render_text,
    render_tui_frame,
    software_risk,
    software_name,
    terminalize_advice_text,
    build_parser,
    truncate,
)


class FormattingTests(unittest.TestCase):
    def test_parser_defaults_to_all_processes(self) -> None:
        args = build_parser().parse_args([])
        self.assertIsNone(args.top)

    def test_parser_accepts_ai_action(self) -> None:
        _, args = parse_cli_args(["ai", "cli", "none", "top", "30"])
        self.assertEqual(args.action, "ai")
        self.assertEqual(args.ai_cli, "none")
        self.assertEqual(args.top, 30)

    def test_parser_keeps_legacy_dash_options_compatible(self) -> None:
        _, args = parse_cli_args(["ai", "--ai-cli", "none", "--top", "30"])
        self.assertEqual(args.action, "ai")
        self.assertEqual(args.ai_cli, "none")
        self.assertEqual(args.top, 30)

    def test_parser_accepts_space_command_options(self) -> None:
        _, args = parse_cli_args(["top", "15", "json", "no", "guide"])
        self.assertIsNone(args.action)
        self.assertEqual(args.top, 15)
        self.assertTrue(args.json)
        self.assertTrue(args.no_guide)

    def test_parser_accepts_completion_action(self) -> None:
        _, args = parse_cli_args(["completion", "zsh"])
        self.assertEqual(args.action, "completion")
        self.assertEqual(args.completion_shell, "zsh")

    def test_parser_accepts_tui_action(self) -> None:
        _, args = parse_cli_args(["tui", "top", "20"])
        self.assertEqual(args.action, "tui")
        self.assertEqual(args.top, 20)

    def test_help_lists_commands_and_sections(self) -> None:
        help_text = build_parser().format_help()
        self.assertIn("常用命令:", help_text)
        self.assertIn("mem ai", help_text)
        self.assertIn("mem optimize", help_text)
        self.assertIn("mem tui", help_text)
        self.assertIn("mem top 20", help_text)
        self.assertIn("mem completion zsh", help_text)
        self.assertNotIn("mem --top", help_text)
        self.assertIn("输出区域:", help_text)

    def test_zsh_completion_script_contains_autosuggest_candidates(self) -> None:
        script = render_completion_script("zsh")
        self.assertIn("#compdef mem", script)
        self.assertIn("_zsh_autosuggest_strategy_mem", script)
        self.assertIn("'mem tui'", script)
        self.assertIn("'mem top 20'", script)
        self.assertIn("'mem ai cli none'", script)

    def test_format_bytes(self) -> None:
        self.assertEqual(format_bytes(0), "0 B")
        self.assertEqual(format_bytes(1024), "1.00 KiB")
        self.assertEqual(format_bytes(10 * 1024**3), "10.0 GiB")

    def test_bar(self) -> None:
        self.assertEqual(bar(50, 100, width=10), "[#####-----]")

    def test_truncate_handles_tiny_widths(self) -> None:
        self.assertEqual(truncate("abcdef", 1), "a")
        self.assertEqual(truncate("abcdef", 2), "ab")
        self.assertEqual(truncate("abcdef", 3), "abc")
        self.assertEqual(truncate("abcdef", 4), "a...")

    def test_terminalize_advice_text_removes_markdown_fences(self) -> None:
        formatted = terminalize_advice_text(
            "建议下一步命令：\n\n```bash\nmem --top 20\nmem --watch 2\n```\n"
        )
        self.assertNotIn("```", formatted)
        self.assertIn("  $ mem top 20", formatted)
        self.assertIn("  $ mem watch 2", formatted)

    def test_software_risk(self) -> None:
        self.assertEqual(
            software_risk(
                SoftwareActivity("hot", 1, 1, rss_bytes=200, vsize_bytes=1, cpu_percent=1.0, top_pid=1),
                total_bytes=1000,
            ),
            "HOT",
        )
        self.assertEqual(
            software_risk(
                SoftwareActivity("warn", 1, 1, rss_bytes=10, vsize_bytes=1, cpu_percent=25.0, top_pid=1),
                total_bytes=1000,
            ),
            "WARN",
        )


class ParsingTests(unittest.TestCase):
    def test_parse_vm_stat(self) -> None:
        stats, page_size = parse_vm_stat(
            """Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                                3901.
Pages active:                            189556.
Pages wired down:                        261106.
"File-backed pages":                       133276.
Pages occupied by compressor:            494798.
"""
        )
        self.assertEqual(page_size, 16384)
        self.assertEqual(stats["pages free"], 3901)
        self.assertEqual(stats["file-backed pages"], 133276)
        self.assertEqual(stats["pages occupied by compressor"], 494798)

    def test_parse_darwin_swap(self) -> None:
        total, used = parse_darwin_swap("vm.swapusage: total = 20480.00M  used = 19728.38M  free = 751.62M")
        self.assertEqual(total, 20480 * 1024**2)
        self.assertEqual(used, int(19728.38 * 1024**2))

    def test_parse_memory_pressure_free_percent(self) -> None:
        self.assertEqual(parse_memory_pressure_free_percent("System-wide memory free percentage: 37%"), 37)

    def test_parse_linux_meminfo(self) -> None:
        values = parse_linux_meminfo(
            """MemTotal:       16384000 kB
MemFree:         1024000 kB
MemAvailable:    8192000 kB
SwapTotal:       2097152 kB
SwapFree:        1048576 kB
"""
        )
        self.assertEqual(values["MemTotal"], 16384000 * 1024)
        self.assertEqual(values["SwapFree"], 1048576 * 1024)

    def test_parse_darwin_display_devices(self) -> None:
        devices = parse_darwin_display_devices(
            """Graphics/Displays:

    Apple M3 Pro:

      Chipset Model: Apple M3 Pro
      Type: GPU
      Bus: Built-In
      Total Number of Cores: 14
      Vendor: Apple (0x106b)
      Metal Support: Metal 4
      Displays:
        Color LCD:
          Resolution: 3024 x 1964 Retina
"""
        )
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0].name, "Apple M3 Pro")
        self.assertEqual(devices[0].cores, 14)
        self.assertEqual(devices[0].displays, ["Color LCD"])

    def test_parse_ioreg_gpu_stats(self) -> None:
        text = (
            '"AGCInfo" = {"fLastSubmissionPID"=70909,"fBusyCount"=0}\n'
            '"PerformanceStatistics" = {"Alloc system memory"=6148456448,'
            '"In use system memory"=1963376640,"Device Utilization %"=56}'
        )
        self.assertEqual(parse_ioreg_agc_info(text)["fLastSubmissionPID"], 70909)
        stats = parse_ioreg_performance_statistics(text)
        self.assertEqual(stats["Alloc system memory"], 6148456448)
        self.assertEqual(stats["Device Utilization %"], 56)

    def test_software_name_prefers_app_bundle(self) -> None:
        self.assertEqual(
            software_name("/Applications/Codex.app/Contents/MacOS/Codex"),
            "Codex",
        )
        self.assertEqual(software_name("/usr/libexec/logd"), "logd")

    def test_app_bundle_name_requires_app_path(self) -> None:
        processes = [
            ProcessMemory(pid=1, rss_bytes=1, cpu_percent=0, software="Framework", command="/System/Foo.framework/x"),
            ProcessMemory(pid=2, rss_bytes=1, cpu_percent=0, software="Chrome", command="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        ]
        self.assertIsNone(app_bundle_name_for_software(processes, "Framework"))
        self.assertEqual(app_bundle_name_for_software(processes, "Chrome"), "Google Chrome")

    def test_quit_command_uses_readable_shell_quoting(self) -> None:
        self.assertEqual(
            quit_command_for_software("Google Chrome"),
            "osascript -e 'tell application \"Google Chrome\" to quit'",
        )


class RenderTests(unittest.TestCase):
    def test_render_text_contains_categories_and_processes(self) -> None:
        snapshot = MemorySnapshot(
            platform="testOS",
            total_bytes=100,
            used_bytes=60,
            available_bytes=40,
            free_bytes=10,
            swap_total_bytes=50,
            swap_used_bytes=5,
            categories=[
                MemoryCategory("used", "已用", 60, "used"),
                MemoryCategory("free", "空闲", 10, "free"),
            ],
            software=[
                SoftwareActivity(
                    name="demo",
                    process_count=1,
                    active_process_count=1,
                    rss_bytes=25,
                    vsize_bytes=50,
                    cpu_percent=1.5,
                    top_pid=123,
                )
            ],
            processes=[
                ProcessMemory(
                    pid=123,
                    ppid=1,
                    rss_bytes=25,
                    vsize_bytes=50,
                    cpu_percent=1.5,
                    memory_percent=25.0,
                    state="R",
                    software="demo",
                    command="/bin/demo",
                )
            ],
            graphics=[
                GraphicsDevice(
                    name="Test GPU",
                    device_type="GPU",
                    vendor="Vendor",
                    cores=8,
                    metal=None,
                    vram_bytes=None,
                    displays=["Display"],
                    utilization_percent=50,
                    renderer_utilization_percent=None,
                    tiler_utilization_percent=None,
                    allocated_system_memory_bytes=40,
                    in_use_system_memory_bytes=20,
                    in_use_driver_memory_bytes=None,
                    last_submission_pid=123,
                    last_submission_process="demo",
                    notes=[],
                )
            ],
            details={},
        )
        rendered = render_text(snapshot)
        self.assertIn("健康", rendered)
        self.assertIn("内存概览", rendered)
        self.assertIn("诊断优先级", rendered)
        self.assertIn("分类", rendered)
        self.assertIn("显卡/GPU", rendered)
        self.assertIn("软件活跃度", rendered)
        self.assertIn("进程明细", rendered)
        self.assertIn("demo", rendered)

    def test_render_tui_frame_contains_tabs_and_footer(self) -> None:
        snapshot = MemorySnapshot(
            platform="testOS",
            total_bytes=1000,
            used_bytes=700,
            available_bytes=300,
            free_bytes=100,
            swap_total_bytes=1000,
            swap_used_bytes=500,
            categories=[],
            software=[
                SoftwareActivity(
                    name="Browser",
                    process_count=3,
                    active_process_count=1,
                    rss_bytes=300,
                    vsize_bytes=500,
                    cpu_percent=12.0,
                    top_pid=42,
                )
            ],
            processes=[
                ProcessMemory(
                    pid=42,
                    ppid=1,
                    rss_bytes=300,
                    vsize_bytes=500,
                    cpu_percent=12.0,
                    memory_percent=30.0,
                    state="S",
                    software="Browser",
                    command="/Applications/Browser.app/Contents/MacOS/Browser",
                )
            ],
            graphics=[],
            details={"pressure_free_percent": 30},
        )
        for view in TUI_VIEWS:
            frame = render_tui_frame(snapshot, view=view, scroll=0, width=80, height=12, top=None)
            rendered = "\n".join(frame.lines)
            self.assertIn("mem TUI", rendered)
            self.assertIn("Tab/1-4", rendered)
            self.assertGreaterEqual(frame.max_scroll, 0)

    def test_overall_status_reflects_swap_pressure(self) -> None:
        snapshot = MemorySnapshot(
            platform="testOS",
            total_bytes=1000,
            used_bytes=700,
            available_bytes=300,
            free_bytes=100,
            swap_total_bytes=1000,
            swap_used_bytes=900,
            categories=[],
            software=[],
            processes=[],
            graphics=[],
            details={},
        )
        self.assertEqual(overall_status(snapshot), "危险")

    def test_guide_commands_include_ai_optimize_watch(self) -> None:
        commands = [item["command"] for item in guide_commands("none")]
        self.assertEqual(commands, ["mem ai", "mem optimize", "mem watch 2"])

    def test_print_output_can_suppress_guidance(self) -> None:
        snapshot = MemorySnapshot(
            platform="testOS",
            total_bytes=100,
            used_bytes=40,
            available_bytes=60,
            free_bytes=60,
            swap_total_bytes=None,
            swap_used_bytes=None,
            categories=[],
            software=[],
            processes=[],
            graphics=[],
            details={},
        )
        args = SimpleNamespace(json=False, no_processes=False, no_guide=False, ai_cli="none")
        output = StringIO()
        with patch("memview.cli.render_guidance", return_value="GUIDE") as render_guidance:
            with redirect_stdout(output):
                print_output(snapshot, args, show_guide=False)
        render_guidance.assert_not_called()
        self.assertNotIn("GUIDE", output.getvalue())

    def test_optimization_plan_skips_non_app_quit_commands(self) -> None:
        snapshot = MemorySnapshot(
            platform="testOS",
            total_bytes=1000,
            used_bytes=900,
            available_bytes=100,
            free_bytes=50,
            swap_total_bytes=1000,
            swap_used_bytes=800,
            categories=[],
            software=[
                SoftwareActivity(
                    name="Framework",
                    process_count=1,
                    active_process_count=1,
                    rss_bytes=512 * 1024**2,
                    vsize_bytes=1,
                    cpu_percent=1.0,
                    top_pid=1,
                )
            ],
            processes=[
                ProcessMemory(
                    pid=1,
                    rss_bytes=512 * 1024**2,
                    cpu_percent=1.0,
                    software="Framework",
                    command="/System/Library/Foo.framework/Foo",
                )
            ],
            graphics=[],
            details={},
        )
        commands = [action.command for action in build_optimization_plan(snapshot)]
        self.assertFalse(any("tell application" in command for command in commands))


class CollectionTests(unittest.TestCase):
    def test_collect_snapshot_summarizes_all_processes_before_limiting_display_rows(self) -> None:
        processes = [
            ProcessMemory(pid=1, rss_bytes=100, cpu_percent=1.0, software="Browser", command="/Applications/Browser.app/a"),
            ProcessMemory(pid=2, rss_bytes=90, cpu_percent=2.0, software="Other", command="/bin/other"),
            ProcessMemory(pid=3, rss_bytes=80, cpu_percent=3.0, software="Browser", command="/Applications/Browser.app/b"),
        ]

        def fake_generic(
            visible_processes: list[ProcessMemory],
            software: list[SoftwareActivity],
        ) -> MemorySnapshot:
            return MemorySnapshot(
                platform="testOS",
                total_bytes=1000,
                used_bytes=500,
                available_bytes=500,
                free_bytes=500,
                swap_total_bytes=None,
                swap_used_bytes=None,
                categories=[],
                software=software,
                processes=visible_processes,
                graphics=[],
                details={},
            )

        with patch("memview.cli.platform.system", return_value="TestOS"):
            with patch("memview.cli.collect_processes", return_value=processes) as collect_processes:
                with patch("memview.cli.collect_generic", side_effect=fake_generic):
                    snapshot = collect_snapshot(process_limit=2)

        collect_processes.assert_called_once_with(limit=None)
        self.assertEqual([item.pid for item in snapshot.processes], [1, 2])
        self.assertEqual(snapshot.software[0].name, "Browser")
        self.assertEqual(snapshot.software[0].rss_bytes, 180)
        self.assertEqual(snapshot.software[0].process_count, 2)


if __name__ == "__main__":
    unittest.main()
