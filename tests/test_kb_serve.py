"""Tests for scripts/kb-serve.py -- the stdlib-only HTTP facade over the
personal knowledgebase vault.

Covers the four HTTP endpoints (via a real ephemeral-port server, so the
actual do_GET/do_POST dispatch is exercised, not just the underlying pure
functions), the enrichment no-op/success/degrade paths, and the two
security-fix cases in find_unenriched_notes(). Everything runs offline:
urllib.request.urlopen / request_enrichment are mocked wherever a real
network call would otherwise happen, and every vault lives under tmp_path,
never the real ~/.knowledgebase.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import sys
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "kb-serve.py"


def _load_kb_serve():
    spec = importlib.util.spec_from_file_location("kb_serve_under_test", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


kb_serve = _load_kb_serve()
KbServeConfig = kb_serve.KbServeConfig


def _config(kb_home: Path, *, enrich_enabled: bool = False, llm_api_key: str | None = None) -> KbServeConfig:
    return KbServeConfig(
        kb_home=kb_home,
        enrich_enabled=enrich_enabled,
        llm_base_url="https://example.invalid/v1",
        llm_model="fake/model",
        llm_api_key=llm_api_key,
    )


@pytest.fixture
def live_server(tmp_path: Path) -> Iterator[tuple[str, KbServeConfig]]:
    """A real kb-serve HTTP server on an ephemeral 127.0.0.1 port, backed
    by an empty vault under tmp_path."""
    config = _config(tmp_path)
    server = kb_serve.KbHTTPServer(("127.0.0.1", 0), kb_serve.KbRequestHandler, config)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield base_url, config
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _post(
    base_url: str,
    path: str,
    payload: dict[str, object],
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, object]]:
    data = json.dumps(payload).encode("utf-8")
    # The service refuses any POST that is not declared JSON, so that a
    # cross-origin browser POST needs a preflight it will never get.
    sent = {"Content-Type": "application/json", **(headers or {})}
    request = urllib.request.Request(
        f"{base_url}{path}", data=data, method="POST", headers=sent,
    )
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


# ── /health ─────────────────────────────────────────────────────────────


def test_health_reports_kb_home_indexed_count_and_ok_status(live_server: tuple[str, KbServeConfig]) -> None:
    base_url, config = live_server
    with urllib.request.urlopen(f"{base_url}/health") as response:
        assert response.status == 200
        body = json.loads(response.read())
    assert body == {"status": "ok", "kb_home": str(config.kb_home), "indexed_count": 0}


# ── security baseline: headers, browser origins, path containment ───────
# See docs/design/security-baseline-threat-model.md. Loopback is not a
# trust boundary: a browser tab can aim JavaScript at 127.0.0.1.


def test_every_response_carries_the_security_header_baseline(
    live_server: tuple[str, KbServeConfig],
) -> None:
    base_url, _ = live_server
    with urllib.request.urlopen(f"{base_url}/health") as response:
        headers = dict(response.headers)
    for name, value in kb_serve.SECURITY_HEADERS.items():
        assert headers[name] == value
    assert headers["Content-Type"] == "application/json; charset=utf-8"


def test_error_response_also_carries_the_security_headers(
    live_server: tuple[str, KbServeConfig],
) -> None:
    base_url, _ = live_server
    try:
        urllib.request.urlopen(f"{base_url}/no-such-route")
        raise AssertionError("expected 404")
    except urllib.error.HTTPError as exc:
        assert exc.code == 404
        assert exc.headers["X-Content-Type-Options"] == "nosniff"


def test_unimplemented_method_reply_also_carries_the_security_headers(
    live_server: tuple[str, KbServeConfig],
) -> None:
    """OPTIONS is answered by the stdlib's own send_error(), not by
    _send_json, so the headers have to be stamped in end_headers()."""
    base_url, _ = live_server
    request = urllib.request.Request(f"{base_url}/health", method="OPTIONS")
    try:
        urllib.request.urlopen(request)
        raise AssertionError("expected an error status")
    except urllib.error.HTTPError as exc:
        assert exc.code == 501
        assert exc.headers["Content-Security-Policy"] == \
            kb_serve.SECURITY_HEADERS["Content-Security-Policy"]
        assert "Access-Control-Allow-Origin" not in exc.headers


def test_cross_origin_post_is_refused_and_writes_nothing(
    live_server: tuple[str, KbServeConfig],
) -> None:
    base_url, config = live_server
    status, body = _post(
        base_url, "/put",
        {"project": "proj1", "title": "Evil", "content": "from a web page"},
        headers={"Origin": "https://evil.example"},
    )
    assert status == 403
    assert "cross-origin" in str(body["error"])
    assert not (config.kb_home / "proj1").exists()


def test_get_with_foreign_host_header_is_refused(
    live_server: tuple[str, KbServeConfig],
) -> None:
    """A DNS-rebound request is same-origin, so it carries no Origin
    header; only the Host header gives it away."""
    base_url, _ = live_server
    request = urllib.request.Request(
        f"{base_url}/health", headers={"Host": "rebind.evil.example"},
    )
    try:
        urllib.request.urlopen(request)
        raise AssertionError("expected 403")
    except urllib.error.HTTPError as exc:
        assert exc.code == 403


def test_post_without_json_content_type_is_refused(
    live_server: tuple[str, KbServeConfig],
) -> None:
    """text/plain is a CORS 'simple request' -- refusing it forces a
    preflight this service never answers."""
    base_url, config = live_server
    status, body = _post(
        base_url, "/put",
        {"project": "proj1", "title": "Evil", "content": "simple request"},
        headers={"Content-Type": "text/plain"},
    )
    assert status == 415
    assert "application/json" in str(body["error"])
    assert not (config.kb_home / "proj1").exists()


@pytest.mark.parametrize(
    "project", ["../escape", "..", "/tmp", "a/b", ".hidden", "proj\x00"],
)
def test_put_rejects_project_names_that_are_not_one_safe_segment(
    live_server: tuple[str, KbServeConfig], project: str,
) -> None:
    base_url, config = live_server
    status, body = _post(
        base_url, "/put", {"project": project, "title": "T", "content": "C"},
    )
    assert status == 400
    assert "project" in str(body["error"])
    assert list(config.kb_home.iterdir()) == []


def test_put_traversal_attempt_writes_nothing_outside_the_vault(
    tmp_path: Path,
) -> None:
    kb_home = tmp_path / "vault"
    kb_home.mkdir()
    outside = tmp_path / "outside"
    config = _config(kb_home)
    with _server_for_config(config) as base_url:
        status, _ = _post(base_url, "/put", {
            "project": "../outside", "title": "Pwned", "content": "x",
        })
    assert status == 400
    assert not outside.exists()


def test_clip_rejects_a_project_dir_symlinked_out_of_the_vault(tmp_path: Path) -> None:
    """The name rule alone cannot see a symlink: 'escape' is a legal
    segment. Only the post-resolve containment check catches it, and the
    clip path delegates its write to kb-clip.py, so the check has to
    happen before the delegation."""
    kb_home = tmp_path / "vault"
    kb_home.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (kb_home / "escape").symlink_to(outside)
    config = _config(kb_home)
    with (
        _server_for_config(config) as base_url,
        patch.object(kb_serve.kb_clip_module(), "clip") as mock_clip,
    ):
        status, body = _post(base_url, "/clip", {
            "url": "https://example.invalid/a", "project": "escape",
        })
    mock_clip.assert_not_called()
    assert status == 400
    assert "escapes the vault root" in str(body["error"])


def test_contained_path_rejects_a_join_that_escapes_the_root(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="escapes the vault root"):
        kb_serve.contained_path(tmp_path, "..", "elsewhere")


# ── /put ────────────────────────────────────────────────────────────────


def test_put_writes_note_with_expected_frontmatter(live_server: tuple[str, KbServeConfig]) -> None:
    base_url, config = live_server
    status, body = _post(base_url, "/put", {
        "project": "proj1", "title": "My Title", "content": "Body text.", "type": "note",
    })
    assert status == 201
    note_path = Path(str(body["path"]))
    assert note_path.is_relative_to(config.kb_home)
    text = note_path.read_text(encoding="utf-8")
    assert 'title: "My Title"' in text
    assert 'project: "proj1"' in text
    assert 'type: "note"' in text
    assert "Body text." in text


def test_put_uses_llm_atomize_when_enrichment_enabled(tmp_path: Path) -> None:
    config = _config(tmp_path, enrich_enabled=True, llm_api_key="fake-key")
    llm_items = [{"title": "Child A", "body": "Body A content."}]
    with (
        _server_for_config(config) as base_url,
        patch.object(kb_serve, "request_atomize_split", return_value=llm_items) as mock_split,
    ):
        status, body = _post(base_url, "/put", {
            "project": "proj1", "title": "Parent Note", "content": "Some parent content.",
        })

    mock_split.assert_called_once()
    assert status == 201
    assert set(body.keys()) == {"path", "children"}
    assert len(body["children"]) == 1
    child_text = Path(str(body["children"][0])).read_text(encoding="utf-8")
    assert 'title: "Child A"' in child_text
    assert "Body A content." in child_text


def test_put_missing_required_field_returns_400(live_server: tuple[str, KbServeConfig]) -> None:
    base_url, _ = live_server
    status, body = _post(base_url, "/put", {"title": "No project or content"})
    assert status == 400
    assert "project" in str(body["error"])


# ── /query ──────────────────────────────────────────────────────────────


def test_query_returns_seeded_note(live_server: tuple[str, KbServeConfig]) -> None:
    base_url, _ = live_server
    _post(base_url, "/put", {
        "project": "proj1", "title": "Distinctive Widget", "content": "widget content zzyzx",
    })
    with urllib.request.urlopen(f"{base_url}/query?q=zzyzx") as response:
        body = json.loads(response.read())
    assert len(body["results"]) == 1
    assert body["results"][0]["title"] == "Distinctive Widget"


def test_query_no_hits_returns_empty_list(live_server: tuple[str, KbServeConfig]) -> None:
    base_url, _ = live_server
    _post(base_url, "/put", {"project": "proj1", "title": "Unrelated", "content": "something else"})
    with urllib.request.urlopen(f"{base_url}/query?q=nosuchtermanywhere") as response:
        body = json.loads(response.read())
    assert body["results"] == []


# ── /enrich: KB_ENRICH=0 default -> zero network calls ────────────────────


def test_enrich_disabled_by_default_makes_zero_network_calls(tmp_path: Path) -> None:
    config = _config(tmp_path, enrich_enabled=False)
    with patch.object(kb_serve, "request_enrichment") as mock_request:
        result = kb_serve.kb_enrich(config, {})
    mock_request.assert_not_called()
    assert result == {"enriched": 0, "message": "KB_ENRICH is 0; enrichment disabled"}


# ── /enrich: KB_ENRICH=1, no resolvable key -> zero network calls ─────────


def test_enrich_enabled_without_key_makes_zero_network_calls(tmp_path: Path) -> None:
    config = _config(tmp_path, enrich_enabled=True, llm_api_key=None)
    with patch.object(kb_serve, "request_enrichment") as mock_request:
        result = kb_serve.kb_enrich(config, {})
    mock_request.assert_not_called()
    assert result["enriched"] == 0
    assert "no API key resolved" in str(result["message"])


# ── /enrich: success path -> rewrites only question/summary ───────────────


def test_enrich_success_rewrites_only_question_and_summary(tmp_path: Path) -> None:
    config = _config(tmp_path, enrich_enabled=True, llm_api_key="fake-key")
    put_result = kb_serve.kb_put(tmp_path, _config(tmp_path), {
        "project": "proj1", "title": "Widget Guide", "content": "This widget does things.",
    })
    note_path = Path(str(put_result["path"]))
    text_before = note_path.read_text(encoding="utf-8")
    body_before = text_before.split("---\n", 2)[2]

    with patch.object(
        kb_serve, "request_enrichment",
        return_value={"question": "What does the widget do?", "summary": "The widget does things well."},
    ) as mock_request:
        result = kb_serve.kb_enrich(config, {})

    mock_request.assert_called_once()
    assert result == {"enriched": 1, "notes": [str(note_path)]}
    text_after = note_path.read_text(encoding="utf-8")
    assert 'question: "What does the widget do?"' in text_after
    assert 'summary: "The widget does things well."' in text_after
    assert 'title: "Widget Guide"' in text_after  # untouched
    assert text_after.split("---\n", 2)[2] == body_before  # body byte-for-byte untouched


# ── security fix: find_unenriched_notes path-escape guard ─────────────────


def test_find_unenriched_notes_rejects_absolute_path_escape(tmp_path: Path) -> None:
    result = kb_serve.find_unenriched_notes(tmp_path, None, "/etc/passwd")
    assert result == []


def test_find_unenriched_notes_rejects_dotdot_relative_escape(tmp_path: Path) -> None:
    kb_home = tmp_path / "vault"
    kb_home.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("secret note content", encoding="utf-8")
    result = kb_serve.find_unenriched_notes(kb_home, None, "../outside.md")
    assert result == []


def test_find_unenriched_notes_happy_path_returns_candidate(tmp_path: Path) -> None:
    put_result = kb_serve.kb_put(tmp_path, _config(tmp_path), {
        "project": "proj1", "title": "Real Note", "content": "content",
    })
    note_path = Path(str(put_result["path"]))
    rel = note_path.relative_to(tmp_path)
    result = kb_serve.find_unenriched_notes(tmp_path, None, str(rel))
    assert result == [note_path.resolve()]


# ── security fix: kb_enrich degrades cleanly on an unreadable note ────────


def test_kb_enrich_degrades_cleanly_when_note_read_fails(tmp_path: Path) -> None:
    """A note that find_unenriched_notes listed but that vanishes/errors
    before read_text() runs must be a clean skip, never an uncaught
    exception, and the return shape stays the normal one."""
    config = _config(tmp_path, enrich_enabled=True, llm_api_key="fake-key")
    vanished_note = tmp_path / "vanished.md"  # never created on disk
    with (
        patch.object(kb_serve, "find_unenriched_notes", return_value=[vanished_note]),
        patch.object(kb_serve, "request_enrichment") as mock_request,
    ):
        result = kb_serve.kb_enrich(config, {})  # must not raise
    mock_request.assert_not_called()  # read_text raised before the network call
    assert result == {"enriched": 0, "notes": []}


# ── secret handling: resolved key never logged on command failure ─────────


def test_resolve_api_key_never_logs_secret_on_command_failure(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """KB_LLM_API_KEY_CMD's own stdout may contain secret-looking text
    even when it fails; that text must never reach the log."""
    secret = "sk-super-secret-fake-12345"
    secret_file = tmp_path / "secret.txt"
    secret_file.write_text(secret, encoding="utf-8")
    # The command text itself carries no secret substring -- only its
    # stdout does, once run -- so this proves the *output*, not just the
    # invocation string, never leaks.
    cmd = f"cat {secret_file}; exit 1"

    with caplog.at_level(logging.WARNING, logger="kb-serve"):
        result = kb_serve.resolve_api_key({"KB_LLM_API_KEY_CMD": cmd})

    assert result is None
    assert secret not in caplog.text
    assert "KB_LLM_API_KEY_CMD failed" in caplog.text  # sanity: the warning path was actually hit


def test_resolve_api_key_falls_back_to_static_key_when_cmd_fails() -> None:
    """A failing KB_LLM_API_KEY_CMD (e.g. a vault CLI missing from the
    container image) must not disable enrichment when a static
    KB_LLM_API_KEY was already injected into the env."""
    result = kb_serve.resolve_api_key({
        "KB_LLM_API_KEY_CMD": "exit 1",
        "KB_LLM_API_KEY": "static-fallback-value",
    })
    assert result == "static-fallback-value"


def test_resolve_api_key_falls_back_to_static_key_when_cmd_stdout_empty() -> None:
    """A KB_LLM_API_KEY_CMD that succeeds but prints nothing is not a
    usable key; fall back to the static KB_LLM_API_KEY."""
    result = kb_serve.resolve_api_key({
        "KB_LLM_API_KEY_CMD": "true",
        "KB_LLM_API_KEY": "static-fallback-value",
    })
    assert result == "static-fallback-value"


# ── /clip ───────────────────────────────────────────────────────────────

_CANNED_HTML = b"""<html>
<head>
<title>Fallback Title</title>
<meta property="og:title" content="Canned OG Title">
<meta property="og:description" content="A canned description of the article.">
<meta property="og:site_name" content="Example Site">
</head>
<body>
<article>
<h1>Canned OG Title</h1>
<p>This is the first canned paragraph with enough text for readability to
consider it the main content block, repeated so it is clearly the densest
node on the page for extraction purposes and passes the minimum content
length heuristics used by the readability library during scoring.</p>
<p>A second paragraph adds more length so the extractor confidently
selects this article body over any boilerplate navigation text that might
otherwise be present on a real page in the wild.</p>
</article>
</body>
</html>"""


class _FakeResponse:
    """Stand-in for what urllib.request.urlopen()'s context manager
    yields -- just enough surface (.read(), .headers.get_content_charset())
    for kb_clip.fetch_html()."""

    def __init__(self, html: bytes) -> None:
        self._html = html
        self.headers = SimpleNamespace(get_content_charset=lambda: "utf-8")

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def read(self) -> bytes:
        return self._html


def _fake_opener(*, html: bytes = b"", exc: Exception | None = None) -> MagicMock:
    """Stand-in for what urllib.request.build_opener(...) returns.
    kb_clip.fetch_html() calls opener.open() directly, never the
    module-level urlopen(), so intercepting its outbound fetch means
    mocking the opener -- matches test_kb_clip.py's own fetch_html
    mocking convention."""
    opener = MagicMock()
    if exc is not None:
        opener.open.side_effect = exc
    else:
        opener.open.return_value = _FakeResponse(html)
    return opener


def test_clip_happy_path_writes_source_note_with_extracted_content(
    live_server: tuple[str, KbServeConfig],
) -> None:
    base_url, config = live_server
    fake_opener = _fake_opener(html=_CANNED_HTML)
    with (
        patch("urllib.request.build_opener", return_value=fake_opener),
        # example.invalid never resolves via real DNS; the SSRF guard is
        # exercised on its own in test_kb_clip.py, not re-derived here.
        patch.object(kb_serve.kb_clip_module(), "check_destination_is_public"),
    ):
        status, body = _post(base_url, "/clip", {"url": "https://example.invalid/article", "project": "proj1"})

    assert status == 201
    external_calls = [c for c in fake_opener.open.call_args_list if "example.invalid" in c.args[0].full_url]
    assert len(external_calls) == 1  # the outbound fetch went through the mock, never the real network

    note_path = Path(str(body["path"]))
    assert note_path.is_relative_to(config.kb_home)
    text = note_path.read_text(encoding="utf-8")
    assert 'type: "source"' in text
    assert 'title: "Canned OG Title"' in text
    assert 'source: "https://example.invalid/article"' in text
    assert "canned paragraph" in text
    assert set(body.keys()) == {"path", "children"}  # no unexpected/leaked fields in the response


def test_clip_fetch_failure_returns_clean_error_and_writes_no_note(tmp_path: Path) -> None:
    """A URLError from the outbound fetch must come back as a clean 502,
    never a 500 stack leak, and must leave the vault untouched. The
    config here carries a fake secret /clip never touches, to prove a
    failure path can't echo it back to the client."""
    secret = "sk-should-never-leak-6f6f6f"  # noqa: S105 test fixture value, not a real secret
    config = _config(tmp_path, llm_api_key=secret)
    server = kb_serve.KbHTTPServer(("127.0.0.1", 0), kb_serve.KbRequestHandler, config)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with (
            patch(
                "urllib.request.build_opener",
                return_value=_fake_opener(exc=urllib.error.URLError("name resolution failed")),
            ),
            # example.invalid never resolves via real DNS; the SSRF guard is
            # exercised on its own in test_kb_clip.py, not re-derived here.
            patch.object(kb_serve.kb_clip_module(), "check_destination_is_public"),
        ):
            status, body = _post(base_url, "/clip", {"url": "https://example.invalid/broken", "project": "proj1"})
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert status == 502
    assert "error" in body
    assert secret not in json.dumps(body)
    assert list(tmp_path.rglob("*.md")) == []  # no partial note written


# ── config resolution: resolve_api_key + build_config ──────────────────


def test_resolve_api_key_cmd_wins_over_static_key_when_both_set() -> None:
    result = kb_serve.resolve_api_key({
        "KB_LLM_API_KEY_CMD": "echo cmd-wins-value",
        "KB_LLM_API_KEY": "static-value-should-lose",
    })
    assert result == "cmd-wins-value"


def test_build_config_enrich_enabled_resolves_key_from_kb_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    for var in ("KB_ENRICH", "KB_LLM_API_KEY", "KB_LLM_API_KEY_CMD"):
        monkeypatch.delenv(var, raising=False)
    (tmp_path / "kb.env").write_text("KB_ENRICH=1\nKB_LLM_API_KEY=env-file-key\n", encoding="utf-8")

    config = kb_serve.build_config(tmp_path)

    assert config.enrich_enabled is True
    assert config.llm_api_key == "env-file-key"


def test_build_config_enrich_disabled_skips_key_resolution_entirely(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """KB_ENRICH absent (default 0) must not even attempt key resolution --
    the same zero-network no-op philosophy kb_enrich itself applies, pinned
    here at the config layer instead."""
    for var in ("KB_ENRICH", "KB_LLM_API_KEY", "KB_LLM_API_KEY_CMD"):
        monkeypatch.delenv(var, raising=False)

    with patch.object(kb_serve, "resolve_api_key") as mock_resolve:
        config = kb_serve.build_config(tmp_path)

    mock_resolve.assert_not_called()
    assert config.enrich_enabled is False
    assert config.llm_api_key is None


# ── apply_enrichment: direct unit test ──────────────────────────────────


def test_apply_enrichment_rewrites_only_question_and_summary_fields(tmp_path: Path) -> None:
    note_path = tmp_path / "note.md"
    note_path.write_text(
        '---\n'
        'type: "note"\n'
        'title: "Sample"\n'
        'question: ""\n'
        'summary: ""\n'
        '---\n\n'
        'Body text.\n',
        encoding="utf-8",
    )

    kb_serve.apply_enrichment(note_path, "What is this?", "It is a sample.")

    text = note_path.read_text(encoding="utf-8")
    assert 'question: "What is this?"' in text
    assert 'summary: "It is a sample."' in text
    assert 'title: "Sample"' in text  # untouched
    assert text.endswith("Body text.\n")  # body untouched


# ── /atomize ─────────────────────────────────────────────────────────────

_ATOMIZE_SECTION_TEXT = "Alpha beta gamma delta epsilon zeta content padding sentence. "


def _long_sectioned_body() -> str:
    """A body comfortably over kb-atomize.py's ATOMIZE_MIN_CHARS (1500)
    with two H2 sections, so the deterministic splitter actually
    produces >=2 children."""
    section = _ATOMIZE_SECTION_TEXT * 20
    return f"## Section One\n\n{section}\n\n## Section Two\n\n{section}\n"


def test_request_atomize_split_small_body_makes_one_model_call(tmp_path: Path) -> None:
    config = _config(tmp_path, enrich_enabled=True, llm_api_key="fake-key")
    with patch.object(
        kb_serve, "_chat_completion_json",
        return_value={"notes": [{"title": "Only Child", "body": "Small body note."}]},
    ) as mock_chat:
        result = kb_serve.request_atomize_split(config, "Small Parent", "Small parent body.")

    mock_chat.assert_called_once()
    assert result == [{"title": "Only Child", "body": "Small body note."}]


def test_request_atomize_split_long_body_keeps_tail_content(tmp_path: Path) -> None:
    config = _config(tmp_path, enrich_enabled=True, llm_api_key="fake-key")
    tail_marker = "tail-marker-survives-chunking"
    body = (
        f"# First Section\n\n{'A' * 7000}\n\n"
        f"# Second Section\n\n{'B' * 7000}\n\n"
        f"# Tail Section\n\n{tail_marker}\n"
    )

    def fake_chat(_config: KbServeConfig, _model: str, prompt: str) -> dict[str, object]:
        if tail_marker in prompt:
            return {"notes": [{"title": "Tail Child", "body": f"Saw {tail_marker}."}]}
        return {"notes": [{"title": "Earlier Child", "body": "Earlier chunk."}]}

    with patch.object(kb_serve, "_chat_completion_json", side_effect=fake_chat) as mock_chat:
        result = kb_serve.request_atomize_split(config, "Long Parent", body)

    assert mock_chat.call_count > 1
    assert {item["title"] for item in result} >= {"Earlier Child", "Tail Child"}
    assert any(tail_marker in item["body"] for item in result)


def test_atomize_degrades_to_deterministic_when_later_chunk_fails(tmp_path: Path) -> None:
    config = _config(tmp_path, enrich_enabled=True, llm_api_key="fake-key")
    body = f"## Section One\n\n{'A' * 7000}\n\n## Section Two\n\n{'B' * 7000}\n"
    with (
        _server_for_config(config) as base_url,
        patch.object(
            kb_serve, "_chat_completion_json",
            side_effect=[
                {"notes": [{"title": "First LLM Child", "body": "First chunk."}]},
                json.JSONDecodeError("bad json", "doc", 0),
            ],
        ) as mock_chat,
    ):
        status, response_body = _post(base_url, "/atomize", {
            "project": "proj1", "title": "Long Parent", "content": body,
        })

    assert mock_chat.call_count == 2
    assert status == 201
    assert response_body["method"] == "deterministic"
    assert len(response_body["children"]) == 2


@contextmanager
def _server_for_config(config: KbServeConfig) -> Iterator[str]:
    """Like the live_server fixture, but for a test-specific config (the
    fixture always builds its own default via _config(tmp_path))."""
    server = kb_serve.KbHTTPServer(("127.0.0.1", 0), kb_serve.KbRequestHandler, config)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield base_url
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_atomize_content_happy_path_returns_llm_children_with_parent_ref(tmp_path: Path) -> None:
    config = _config(tmp_path, enrich_enabled=True, llm_api_key="fake-key")
    llm_items = [
        {"title": "First Child", "body": "First child body."},
        {"title": "Second Child", "body": "Second child body."},
    ]
    with (
        _server_for_config(config) as base_url,
        patch.object(kb_serve, "request_atomize_split", return_value=llm_items) as mock_split,
    ):
        status, body = _post(base_url, "/atomize", {
            "project": "proj1", "title": "Parent Note", "content": "Some parent content.",
        })

    assert status == 201
    mock_split.assert_called_once()
    assert body["method"] == "llm"
    parent_path = Path(str(body["parent"]))
    assert parent_path.is_relative_to(config.kb_home)
    children = [Path(str(p)) for p in body["children"]]
    assert len(children) == 2
    for child_path, item in zip(children, llm_items, strict=True):
        assert child_path.is_relative_to(config.kb_home)
        text = child_path.read_text(encoding="utf-8")
        assert f'title: "{item["title"]}"' in text
        assert item["body"] in text
        assert f'parent: "{parent_path}"' in text


def test_atomize_url_happy_path_returns_llm_children(tmp_path: Path) -> None:
    config = _config(tmp_path, enrich_enabled=True, llm_api_key="fake-key")
    llm_items = [{"title": "Child A", "body": "Body A content."}]
    with (
        _server_for_config(config) as base_url,
        patch("urllib.request.build_opener", return_value=_fake_opener(html=_CANNED_HTML)),
        patch.object(kb_serve, "request_atomize_split", return_value=llm_items) as mock_split,
        # example.invalid never resolves via real DNS; the SSRF guard is
        # exercised on its own in test_kb_clip.py, not re-derived here.
        patch.object(kb_serve.kb_clip_module(), "check_destination_is_public"),
    ):
        status, body = _post(base_url, "/atomize", {"url": "https://example.invalid/article", "project": "proj1"})

    assert status == 201
    mock_split.assert_called_once()
    assert body["method"] == "llm"
    parent_path = Path(str(body["parent"]))
    assert 'title: "Canned OG Title"' in parent_path.read_text(encoding="utf-8")
    children = [Path(str(p)) for p in body["children"]]
    assert len(children) == 1
    text = children[0].read_text(encoding="utf-8")
    assert 'title: "Child A"' in text
    assert "Body A content." in text


def test_atomize_deterministic_fallback_when_enrich_disabled(tmp_path: Path) -> None:
    config = _config(tmp_path, enrich_enabled=False)
    with (
        _server_for_config(config) as base_url,
        patch.object(kb_serve, "request_atomize_split") as mock_split,
    ):
        status, body = _post(base_url, "/atomize", {
            "project": "proj1", "title": "Long Parent", "content": _long_sectioned_body(),
        })

    mock_split.assert_not_called()
    assert status == 201
    assert body["method"] == "deterministic"
    assert len(body["children"]) == 2


def test_atomize_degrades_to_deterministic_on_llm_failure(tmp_path: Path) -> None:
    config = _config(tmp_path, enrich_enabled=True, llm_api_key="fake-key")
    with (
        _server_for_config(config) as base_url,
        patch.object(
            kb_serve, "request_atomize_split",
            side_effect=json.JSONDecodeError("bad json", "doc", 0),
        ) as mock_split,
    ):
        status, body = _post(base_url, "/atomize", {
            "project": "proj1", "title": "Long Parent", "content": _long_sectioned_body(),
        })

    mock_split.assert_called_once()
    assert status == 201
    assert body["method"] == "deterministic"
    assert len(body["children"]) == 2


def test_atomize_degrades_to_deterministic_on_llm_value_error(tmp_path: Path) -> None:
    """A malformed-but-valid-JSON LLM response (e.g. 'notes' present but
    not a list) raises ValueError from request_atomize_split's own
    parsing; that must degrade too, not 500."""
    config = _config(tmp_path, enrich_enabled=True, llm_api_key="fake-key")
    with (
        _server_for_config(config) as base_url,
        patch.object(
            kb_serve, "request_atomize_split",
            side_effect=ValueError("malformed atomize response"),
        ) as mock_split,
    ):
        status, body = _post(base_url, "/atomize", {
            "project": "proj1", "title": "Long Parent", "content": _long_sectioned_body(),
        })

    mock_split.assert_called_once()
    assert status == 201
    assert body["method"] == "deterministic"
    assert len(body["children"]) == 2


def test_atomize_missing_project_returns_400(live_server: tuple[str, KbServeConfig]) -> None:
    base_url, _ = live_server
    status, body = _post(base_url, "/atomize", {"content": "some content"})
    assert status == 400
    assert "project" in str(body["error"])


def test_atomize_missing_url_and_content_returns_400(live_server: tuple[str, KbServeConfig]) -> None:
    base_url, _ = live_server
    status, body = _post(base_url, "/atomize", {"project": "proj1"})
    assert status == 400
    assert "url" in str(body["error"]) or "content" in str(body["error"])


def test_atomize_both_url_and_content_given_prefers_url(tmp_path: Path) -> None:
    """Pins the real dispatch order (`if url: ... elif content:`) rather
    than inventing a stricter contract: url wins when both are given."""
    config = _config(tmp_path)
    with (
        _server_for_config(config) as base_url,
        patch("urllib.request.build_opener", return_value=_fake_opener(html=_CANNED_HTML)),
        # example.invalid never resolves via real DNS; the SSRF guard is
        # exercised on its own in test_kb_clip.py, not re-derived here.
        patch.object(kb_serve.kb_clip_module(), "check_destination_is_public"),
    ):
        status, body = _post(base_url, "/atomize", {
            "project": "proj1",
            "url": "https://example.invalid/article",
            "content": "This content must be ignored since url wins.",
        })

    assert status == 201
    text = Path(str(body["parent"])).read_text(encoding="utf-8")
    assert "canned paragraph" in text
    assert "must be ignored" not in text
