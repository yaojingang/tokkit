from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Mapping

from .utils import format_seconds


DEFAULT_REPORT_MODEL = os.environ.get("VIDBRIEF_REPORT_MODEL", "gpt-4.1-mini")
DEFAULT_TRANSCRIBE_MODEL = os.environ.get("VIDBRIEF_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe")


class AIError(RuntimeError):
    pass


def choose_report_provider(requested: str) -> str:
    if requested != "auto":
        return requested
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    if shutil.which("codex"):
        return "codex"
    return "none"


def build_report_prompt(metadata: Mapping[str, Any], transcript: str, *, language: str = "zh-CN") -> str:
    title = metadata.get("title") or metadata.get("fulltitle") or "Untitled video"
    url = metadata.get("webpage_url") or metadata.get("original_url") or ""
    duration = format_seconds(metadata.get("duration"))
    uploader = metadata.get("uploader") or metadata.get("channel") or ""
    description = str(metadata.get("description") or "").strip()
    if len(description) > 1200:
        description = f"{description[:1200].rstrip()}..."

    return f"""You are a precise video analyst. Generate a useful Markdown report in {language}.

Report requirements:
- Start with a short executive summary.
- Extract the key arguments, facts, claims, examples, and action items.
- Include a timeline when the transcript gives enough sequence information.
- Separate direct observations from reasonable inferences.
- Keep the report concise but specific.

Video metadata:
- Title: {title}
- URL: {url}
- Uploader: {uploader}
- Duration: {duration}
- Description: {description}

Transcript:
{transcript}
"""


def generate_report(
    prompt: str,
    *,
    provider: str,
    output_dir: Path,
    model: str | None = None,
    timeout_seconds: int = 900,
) -> str:
    provider = choose_report_provider(provider)
    if provider == "openai":
        return generate_report_openai(prompt, model=model or DEFAULT_REPORT_MODEL)
    if provider == "codex":
        return generate_report_codex(prompt, output_dir=output_dir, model=model, timeout_seconds=timeout_seconds)
    if provider == "none":
        return generate_report_none(prompt)
    raise AIError(f"unknown report provider: {provider}")


def generate_report_openai(prompt: str, *, model: str = DEFAULT_REPORT_MODEL) -> str:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise AIError("OpenAI provider requires: python3 -m pip install -e '.[openai]'") from exc
    if not os.environ.get("OPENAI_API_KEY"):
        raise AIError("OPENAI_API_KEY is required for the OpenAI provider")

    client = OpenAI()
    response = client.responses.create(model=model, input=prompt)
    output_text = getattr(response, "output_text", None)
    if output_text:
        return str(output_text).strip()
    return str(response).strip()


def generate_report_codex(
    prompt: str,
    *,
    output_dir: Path,
    model: str | None = None,
    timeout_seconds: int = 900,
) -> str:
    codex = shutil.which("codex")
    if not codex:
        raise AIError("codex CLI was not found on PATH")

    safe_prompt = (
        "Read the transcript and output only the final Markdown report. "
        "Do not edit files, do not run commands, and do not include process commentary.\n\n"
        f"{prompt}"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, dir=output_dir) as handle:
        output_path = Path(handle.name)

    command = [codex]
    if model:
        command.extend(["--model", model])
    command.extend(
        [
            "-a",
            "never",
            "exec",
            "--skip-git-repo-check",
            "--ephemeral",
            "--sandbox",
            "read-only",
            "--output-last-message",
            str(output_path),
            "-",
        ]
    )

    completed = subprocess.run(
        command,
        input=safe_prompt,
        text=True,
        capture_output=True,
        cwd=output_dir,
        timeout=timeout_seconds,
    )
    if completed.returncode != 0:
        output_path.unlink(missing_ok=True)
        detail = (completed.stderr or completed.stdout).strip()
        raise AIError(f"codex report generation failed: {detail}")

    text = output_path.read_text(encoding="utf-8", errors="replace").strip()
    output_path.unlink(missing_ok=True)
    return text or completed.stdout.strip()


def generate_report_none(prompt: str) -> str:
    transcript_marker = "Transcript:\n"
    transcript = prompt.split(transcript_marker, 1)[-1].strip() if transcript_marker in prompt else prompt
    preview = transcript[:6000].rstrip()
    if len(transcript) > len(preview):
        preview = f"{preview}\n\n[Transcript truncated in non-AI mode.]"
    return f"""# Video Report

AI provider was not configured, so this is a deterministic report shell.

## Transcript Preview

{preview}
"""


def transcribe_audio_openai(
    audio_files: list[Path],
    *,
    model: str = DEFAULT_TRANSCRIBE_MODEL,
    language: str | None = None,
    prompt: str | None = None,
) -> str:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise AIError("OpenAI transcription requires: python3 -m pip install -e '.[openai]'") from exc
    if not os.environ.get("OPENAI_API_KEY"):
        raise AIError("OPENAI_API_KEY is required for OpenAI transcription")

    client = OpenAI()
    parts: list[str] = []
    for index, audio_file in enumerate(audio_files, start=1):
        with audio_file.open("rb") as handle:
            kwargs: dict[str, Any] = {
                "model": model,
                "file": handle,
                "response_format": "text",
            }
            if language:
                kwargs["language"] = language
            if prompt:
                kwargs["prompt"] = prompt
            result = client.audio.transcriptions.create(**kwargs)
        text = str(result).strip()
        if text:
            if len(audio_files) > 1:
                parts.append(f"[Chunk {index}]\n{text}")
            else:
                parts.append(text)
    return "\n\n".join(parts).strip()
