from __future__ import annotations

import json
import os
import re
import shutil
import stat
from dataclasses import asdict, dataclass
from pathlib import Path


PATCH_START_MARKER = "/* TOKKIT_AUGMENT_CAPTURE_START */"
PATCH_END_MARKER = "/* TOKKIT_AUGMENT_CAPTURE_END */"
PATCH_VERSION = "1"
_AUGMENT_DIR_RE = re.compile(r"augment\.vscode-augment-(\d+(?:\.\d+)+)$")


@dataclass(slots=True)
class AugmentPatchStatus:
    extension_dir: str | None
    extension_js: str | None
    backup_path: str | None
    installed_versions: list[str]
    extension_exists: bool
    patched: bool
    backup_exists: bool
    capture_path: str
    patch_version: str


def discover_augment_extensions() -> list[Path]:
    root = Path.home() / ".vscode/extensions"
    if not root.exists():
        return []
    candidates = [path for path in root.glob("augment.vscode-augment-*") if path.is_dir()]
    return sorted(candidates, key=_sort_key_for_extension, reverse=True)


def inspect_augment_patch(*, extension_dir: Path | None = None, capture_path: Path) -> AugmentPatchStatus:
    installed = discover_augment_extensions()
    selected_dir = extension_dir or (installed[0] if installed else None)
    extension_js = selected_dir / "out/extension.js" if selected_dir else None
    backup_path = extension_js.with_suffix(".js.tokkit.bak") if extension_js else None
    patched = False
    if extension_js and extension_js.exists():
        try:
            text = extension_js.read_text(encoding="utf-8")
            patched = PATCH_START_MARKER in text and PATCH_END_MARKER in text
        except OSError:
            patched = False
    return AugmentPatchStatus(
        extension_dir=str(selected_dir) if selected_dir else None,
        extension_js=str(extension_js) if extension_js else None,
        backup_path=str(backup_path) if backup_path else None,
        installed_versions=[path.name for path in installed],
        extension_exists=bool(extension_js and extension_js.exists()),
        patched=patched,
        backup_exists=bool(backup_path and backup_path.exists()),
        capture_path=str(capture_path),
        patch_version=PATCH_VERSION,
    )


def apply_augment_capture_patch(*, extension_dir: Path | None = None, capture_path: Path) -> AugmentPatchStatus:
    status = inspect_augment_patch(extension_dir=extension_dir, capture_path=capture_path)
    if not status.extension_exists or not status.extension_js:
        raise RuntimeError("Augment VS Code extension not found.")

    extension_js = Path(status.extension_js)
    backup_path = Path(status.backup_path) if status.backup_path else extension_js.with_suffix(".js.tokkit.bak")
    original = extension_js.read_text(encoding="utf-8")
    if not backup_path.exists():
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(extension_js, backup_path)

    patch_block = _build_patch_block()
    updated = _replace_or_append_patch(original, patch_block)
    if updated != original:
        _ensure_owner_writable(extension_js)
        extension_js.write_text(updated, encoding="utf-8")
    return inspect_augment_patch(extension_dir=extension_dir, capture_path=capture_path)


def remove_augment_capture_patch(*, extension_dir: Path | None = None, capture_path: Path) -> AugmentPatchStatus:
    status = inspect_augment_patch(extension_dir=extension_dir, capture_path=capture_path)
    if not status.extension_exists or not status.extension_js:
        raise RuntimeError("Augment VS Code extension not found.")

    extension_js = Path(status.extension_js)
    backup_path = Path(status.backup_path) if status.backup_path else extension_js.with_suffix(".js.tokkit.bak")
    if backup_path.exists():
        _ensure_owner_writable(extension_js)
        shutil.copy2(backup_path, extension_js)
        return inspect_augment_patch(extension_dir=extension_dir, capture_path=capture_path)

    original = extension_js.read_text(encoding="utf-8")
    updated = _strip_patch_block(original)
    if updated != original:
        _ensure_owner_writable(extension_js)
        extension_js.write_text(updated, encoding="utf-8")
    return inspect_augment_patch(extension_dir=extension_dir, capture_path=capture_path)


def status_payload(status: AugmentPatchStatus) -> dict[str, object]:
    return asdict(status)


def _sort_key_for_extension(path: Path) -> tuple[int, ...]:
    match = _AUGMENT_DIR_RE.search(path.name)
    if not match:
        return (0,)
    return tuple(int(part) for part in match.group(1).split("."))


def _replace_or_append_patch(original: str, patch_block: str) -> str:
    if PATCH_START_MARKER in original and PATCH_END_MARKER in original:
        return _strip_patch_block(original).rstrip() + "\n\n" + patch_block + "\n"
    suffix = "" if original.endswith("\n") else "\n"
    return original + suffix + "\n" + patch_block + "\n"


def _strip_patch_block(original: str) -> str:
    pattern = re.compile(
        re.escape(PATCH_START_MARKER) + r".*?" + re.escape(PATCH_END_MARKER) + r"\n?",
        re.DOTALL,
    )
    return pattern.sub("", original).rstrip() + "\n"


def _build_patch_block() -> str:
    patch_source = f"""
{PATCH_START_MARKER}
;(() => {{
  try {{
    const fs = require("fs");
    const os = require("os");
    const path = require("path");
    const PATCH_VERSION = {json.dumps(PATCH_VERSION)};
    const originalFetch = globalThis.fetch;
    if (typeof originalFetch !== "function" || originalFetch.__tokkitAugmentWrapped) {{
      return;
    }}

    function resolveCapturePath() {{
      const explicit =
        (process.env.TOKKIT_AUGMENT_CAPTURE_PATH && process.env.TOKKIT_AUGMENT_CAPTURE_PATH.trim()) ||
        (process.env.TOKSTAT_AUGMENT_CAPTURE_PATH && process.env.TOKSTAT_AUGMENT_CAPTURE_PATH.trim());
      if (explicit) {{
        return explicit;
      }}
      const home =
        (process.env.TOKKIT_HOME && process.env.TOKKIT_HOME.trim()) ||
        (process.env.TOKSTAT_HOME && process.env.TOKSTAT_HOME.trim()) ||
        path.join(os.homedir(), ".tokkit");
      return path.join(home, "augment-usage.ndjson");
    }}

    function headersToObject(headersLike) {{
      if (!headersLike) return {{}};
      if (typeof Headers !== "undefined" && headersLike instanceof Headers) {{
        return Object.fromEntries(headersLike.entries());
      }}
      if (Array.isArray(headersLike)) {{
        return Object.fromEntries(headersLike);
      }}
      if (typeof headersLike === "object") {{
        return Object.fromEntries(
          Object.entries(headersLike).map(([key, value]) => [String(key), String(value)])
        );
      }}
      return {{}};
    }}

    function parseJsonBody(body) {{
      if (body == null) return null;
      try {{
        const raw =
          typeof body === "string"
            ? body
            : Buffer.isBuffer(body)
              ? body.toString("utf-8")
              : ArrayBuffer.isView(body)
                ? Buffer.from(body.buffer, body.byteOffset, body.byteLength).toString("utf-8")
                : null;
        if (!raw) return null;
        return JSON.parse(raw);
      }} catch {{
        return null;
      }}
    }}

    function normalizeUsage(candidate) {{
      if (!candidate || typeof candidate !== "object") return null;
      const numericKeys = [
        "input_tokens",
        "output_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
      ];
      const hasAny = numericKeys.some((key) => typeof candidate[key] === "number");
      if (!hasAny) return null;
      return {{
        input_tokens: Number(candidate.input_tokens || 0),
        output_tokens: Number(candidate.output_tokens || 0),
        cache_read_input_tokens: Number(candidate.cache_read_input_tokens || 0),
        cache_creation_input_tokens: Number(candidate.cache_creation_input_tokens || 0),
      }};
    }}

    function extractCandidates(value, state) {{
      if (value == null) return;
      if (Array.isArray(value)) {{
        for (const item of value) extractCandidates(item, state);
        return;
      }}
      if (typeof value !== "object") return;

      const usage = normalizeUsage(value);
      if (usage) state.usages.push(usage);

      if (typeof value.credits_consumed === "number") {{
        state.billings.push({{
          credits_consumed: Number(value.credits_consumed),
          transaction_id: typeof value.transaction_id === "string" ? value.transaction_id : "",
        }});
      }}

      for (const key of ["model_id", "model", "response_model"]) {{
        if (typeof value[key] === "string" && value[key].trim()) {{
          state.models.push(value[key].trim());
        }}
      }}

      for (const nested of Object.values(value)) {{
        extractCandidates(nested, state);
      }}
    }}

    function usageTotal(usage) {{
      return (
        Number(usage.input_tokens || 0) +
        Number(usage.output_tokens || 0) +
        Number(usage.cache_read_input_tokens || 0) +
        Number(usage.cache_creation_input_tokens || 0)
      );
    }}

    function bestUsage(usages) {{
      let best = null;
      for (const usage of usages) {{
        if (!best || usageTotal(usage) >= usageTotal(best)) {{
          best = usage;
        }}
      }}
      return best;
    }}

    function bestBilling(billings) {{
      let best = null;
      for (const billing of billings) {{
        if (!best || Number(billing.credits_consumed || 0) >= Number(best.credits_consumed || 0)) {{
          best = billing;
        }}
      }}
      return best;
    }}

    function shouldCapture(url, headers) {{
      const requestId = headers["x-request-id"] || headers["X-Request-Id"];
      const sessionId = headers["x-request-session-id"] || headers["X-Request-Session-Id"];
      if (!requestId || !sessionId) return false;
      try {{
        const parsed = new URL(url);
        const pathname = parsed.pathname;
        return /(?:^|\\/)(chat-stream|prompt-enhancer|chat-input-completion|complete|resolve-next-edit|smart-paste|remote-agents\\/list-stream|remote-agents\\/agent-history-stream)$/.test(pathname);
      }} catch {{
        return false;
      }}
    }}

    async function readResponseLines(response, onLine) {{
      if (!response.body || typeof response.body.getReader !== "function") {{
        const text = await response.text();
        for (const line of text.split(/\\r?\\n/)) {{
          if (line.trim()) onLine(line.trim());
        }}
        return;
      }}
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      try {{
        while (true) {{
          const chunk = await reader.read();
          if (chunk.done) break;
          buffer += decoder.decode(chunk.value, {{ stream: true }});
          let lineBreak = buffer.indexOf("\\n");
          while (lineBreak !== -1) {{
            const line = buffer.slice(0, lineBreak).trim();
            buffer = buffer.slice(lineBreak + 1);
            if (line) onLine(line);
            lineBreak = buffer.indexOf("\\n");
          }}
        }}
        buffer += decoder.decode();
        const tail = buffer.trim();
        if (tail) onLine(tail);
      }} finally {{
        try {{
          await reader.cancel();
        }} catch {{}}
      }}
    }}

    function writeCaptureLine(payload) {{
      try {{
        const capturePath = resolveCapturePath();
        fs.mkdirSync(path.dirname(capturePath), {{ recursive: true }});
        fs.appendFileSync(capturePath, JSON.stringify(payload) + "\\n", "utf8");
      }} catch {{}}
    }}

    async function captureResponse(context, response) {{
      const state = {{
        usages: [],
        billings: [],
        models: [],
      }};

      try {{
        await readResponseLines(response, (line) => {{
          try {{
            extractCandidates(JSON.parse(line), state);
          }} catch {{}}
        }});
      }} catch {{
        return;
      }}

      const usage = bestUsage(state.usages);
      const billing = bestBilling(state.billings);
      if (!usage && !billing) return;

      writeCaptureLine({{
        kind: "augment_usage_capture",
        capture_version: PATCH_VERSION,
        captured_at: new Date().toISOString(),
        started_at: context.startedAt,
        request_id: context.requestId,
        session_id: context.sessionId,
        source: "augment:vscode",
        endpoint: context.endpoint,
        url: context.url,
        method: context.method,
        request_model: context.requestModel,
        response_model: state.models[0] || "",
        conversation_id: context.conversationId,
        mode: context.mode,
        path: context.pathName,
        workspace: context.workspace,
        input_tokens: usage ? usage.input_tokens : 0,
        output_tokens: usage ? usage.output_tokens : 0,
        cache_read_input_tokens: usage ? usage.cache_read_input_tokens : 0,
        cache_creation_input_tokens: usage ? usage.cache_creation_input_tokens : 0,
        credits_consumed: billing ? billing.credits_consumed : null,
        transaction_id: billing ? billing.transaction_id : "",
        response_status: response.status,
      }});
    }}

    async function wrappedFetch(input, init) {{
      const url =
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.href
            : input && typeof input.url === "string"
              ? input.url
              : "";
      const headers = headersToObject(init && init.headers);
      if (!shouldCapture(url, headers)) {{
        return originalFetch.call(this, input, init);
      }}

      const body = parseJsonBody(init && init.body);
      const endpoint = (() => {{
        try {{
          return new URL(url).pathname.replace(/^\\/+/, "");
        }} catch {{
          return "";
        }}
      }})();
      const context = {{
        startedAt: new Date().toISOString(),
        requestId: headers["x-request-id"] || headers["X-Request-Id"] || "",
        sessionId: headers["x-request-session-id"] || headers["X-Request-Session-Id"] || "",
        url,
        method: (init && init.method) || "GET",
        endpoint,
        requestModel: body && typeof body.model === "string" ? body.model : "",
        conversationId: body && typeof body.conversation_id === "string" ? body.conversation_id : "",
        mode: body && typeof body.mode === "string" ? body.mode : "",
        pathName: body && typeof body.path === "string" ? body.path : "",
        workspace: body && typeof body.workspace_root === "string" ? body.workspace_root : "",
      }};

      const response = await originalFetch.call(this, input, init);
      try {{
        void captureResponse(context, response.clone());
      }} catch {{}}
      return response;
    }}

    wrappedFetch.__tokkitAugmentWrapped = true;
    globalThis.fetch = wrappedFetch;
  }} catch {{}}
}})();
{PATCH_END_MARKER}
    """.strip()
    return patch_source


def _ensure_owner_writable(path: Path) -> None:
    current_mode = path.stat().st_mode
    if current_mode & stat.S_IWUSR:
        return
    os.chmod(path, current_mode | stat.S_IWUSR)
