"""LWSM-1187 — which browsers the desktop offers, and launching one.

No Qt at all, not even `QtCore`: `browsers.py` is core (`coding.md § O1`), so
every rule here is exercised with no display and no `qtbot`.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from lwsm import browsers
from lwsm.browsers import Browser, BrowserError
from lwsm.configfile import MAX_FILE_BYTES

FIREFOX = """\
[Desktop Entry]
Type=Application
Name=Firefox
Exec=/usr/bin/firefox %u
MimeType=text/html;x-scheme-handler/http;x-scheme-handler/https;
"""


def write(directory: Path, name: str, text: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(text)
    return path


def entry(**overrides: str) -> str:
    """A minimal valid browser entry with named lines replaced or added."""
    fields = {
        "Type": "Application",
        "Name": "Test Browser",
        "Exec": "/usr/bin/testbrowser %u",
        "MimeType": "x-scheme-handler/http;",
    }
    fields.update(overrides)
    body = "\n".join(f"{key}={value}" for key, value in fields.items())
    return f"[Desktop Entry]\n{body}\n"


# --------------------------------------------------------------------------
# parse_exec — the spec's quoting rules, without a shell
# --------------------------------------------------------------------------


def test_parse_exec_splits_on_unquoted_whitespace() -> None:
    assert browsers.parse_exec("/usr/bin/firefox  --new-tab %u") == (
        "/usr/bin/firefox",
        "--new-tab",
        "%u",
    )


def test_parse_exec_keeps_a_quoted_path_whole() -> None:
    """A space in a program path must not become two arguments.

    This is the rule that makes parsing worth doing at all rather than
    `str.split`, and the one a naive split gets wrong.
    """
    assert browsers.parse_exec('"/opt/My Browser/run" %u') == (
        "/opt/My Browser/run",
        "%u",
    )


def test_parse_exec_honours_a_backslash_escape_inside_quotes() -> None:
    assert browsers.parse_exec('"a\\"b" %u') == ('a"b', "%u")


def test_parse_exec_of_an_empty_value_is_empty() -> None:
    assert browsers.parse_exec("   ") == ()


# --------------------------------------------------------------------------
# expand — field codes
# --------------------------------------------------------------------------


@pytest.mark.parametrize("code", ["%u", "%U", "%f", "%F"])
def test_expand_substitutes_the_url_for_each_url_code(code: str) -> None:
    assert browsers.expand(("/bin/b", code), "http://localhost:3000/") == (
        "/bin/b",
        "http://localhost:3000/",
    )


@pytest.mark.parametrize("code", ["%d", "%D", "%n", "%N", "%v", "%m", "%i", "%c", "%k"])
def test_expand_drops_a_code_it_carries_no_value_for(code: str) -> None:
    """Dropped, never passed through.

    `%i` is the sharp one: it expands to *two* arguments or to none, so leaving
    it in place hands the browser a literal `%i` to open.
    """
    assert browsers.expand(("/bin/b", code, "%u"), "http://x/") == (
        "/bin/b",
        "http://x/",
    )


def test_expand_appends_the_url_when_the_entry_declares_no_code() -> None:
    assert browsers.expand(("/bin/b", "--new-tab"), "http://x/") == (
        "/bin/b",
        "--new-tab",
        "http://x/",
    )


def test_expand_leaves_flatpaks_file_forwarding_markers_alone() -> None:
    """A real entry shape, taken from this machine's installed Brave (2026-08-24).

    `@@u` and `@@` are not Desktop Entry field codes — they are Flatpak's own
    file-forwarding markers, and `flatpak run --file-forwarding` consumes them
    itself, treating what sits between them as URIs (`man flatpak-run`,
    verified rather than assumed). So passing them through with the URL between
    them is correct, and stripping or substituting them would break every
    Flatpak browser.

    No fixture author would have invented this; it came from running the real
    matcher over the real 381-entry population, which is the only thing that
    answers "what else did this match?".
    """
    argv = (
        "/usr/bin/flatpak",
        "run",
        "--command=brave",
        "--file-forwarding",
        "com.brave.Browser",
        "@@u",
        "%U",
        "@@",
    )
    assert browsers.expand(argv, "http://localhost:3000/") == (
        "/usr/bin/flatpak",
        "run",
        "--command=brave",
        "--file-forwarding",
        "com.brave.Browser",
        "@@u",
        "http://localhost:3000/",
        "@@",
    )


def test_expand_unescapes_a_literal_percent() -> None:
    assert browsers.expand(("/bin/b", "100%%", "%u"), "http://x/") == (
        "/bin/b",
        "100%",
        "http://x/",
    )


# --------------------------------------------------------------------------
# installed — which entries count as a browser
# --------------------------------------------------------------------------


def test_an_http_handler_is_offered(tmp_path: Path) -> None:
    write(tmp_path, "firefox.desktop", FIREFOX)
    found = browsers.installed((tmp_path,))
    assert [b.entry_id for b in found] == ["firefox.desktop"]
    assert found[0].name == "Firefox"
    assert found[0].argv == ("/usr/bin/firefox", "%u")


def test_an_entry_that_handles_no_http_scheme_is_not_a_browser(tmp_path: Path) -> None:
    write(tmp_path, "editor.desktop", entry(MimeType="text/plain;"))
    assert browsers.installed((tmp_path,)) == ()


@pytest.mark.parametrize("key", ["NoDisplay", "Hidden"])
def test_an_entry_the_desktop_hides_is_not_offered(tmp_path: Path, key: str) -> None:
    write(tmp_path, "b.desktop", entry(**{key: "true"}))
    assert browsers.installed((tmp_path,)) == ()


def test_a_non_application_entry_is_not_offered(tmp_path: Path) -> None:
    write(tmp_path, "b.desktop", entry(Type="Link"))
    assert browsers.installed((tmp_path,)) == ()


def test_an_entry_with_no_exec_is_not_offered(tmp_path: Path) -> None:
    write(tmp_path, "b.desktop", entry(Exec=""))
    assert browsers.installed((tmp_path,)) == ()


def test_a_desktop_action_group_cannot_supply_the_exec(tmp_path: Path) -> None:
    """The Exec must come from `[Desktop Entry]`, never from an action group.

    A real browser entry carries actions like "New Private Window", each with
    its own `Exec=`. Reading past the group header would launch the action
    instead of the browser — and it would look almost right, which is what
    makes it worth a test.
    """
    write(
        tmp_path,
        "b.desktop",
        entry()
        + "\n[Desktop Action new-private-window]\nExec=/usr/bin/wrong --private\n",
    )
    (found,) = browsers.installed((tmp_path,))
    assert found.argv == ("/usr/bin/testbrowser", "%u")


def test_an_action_groups_mimetype_cannot_make_an_entry_a_browser(
    tmp_path: Path,
) -> None:
    """The group header is what stops the scan, and `setdefault` is not enough.

    The Exec test above cannot see this, and neither could a first draft of this
    one: first-key-wins protects any key `[Desktop Entry]` DECLARES, so both
    stayed green under the mutation. What has no backstop is a key the entry
    group omits entirely -- here an application that is not a browser at all,
    beside an action group that names the http handler. A scan that does not
    stop at the header adopts it and offers a text editor as a browser.
    """
    write(
        tmp_path,
        "editor.desktop",
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Editor\n"
        "Exec=/usr/bin/editor %f\n"
        "\n"
        "[Desktop Action open-link]\n"
        "MimeType=x-scheme-handler/http;\n",
    )
    assert browsers.installed((tmp_path,)) == ()


def test_an_entry_whose_tryexec_binary_is_gone_is_not_offered(tmp_path: Path) -> None:
    """A stale entry for an uninstalled browser must not reach the dropdown.

    Offering it means the user picks a browser that then fails at the click,
    which reads as the app being broken rather than the entry being stale.
    """
    write(tmp_path, "b.desktop", entry(TryExec="/nonexistent/definitely-not-here"))
    assert browsers.installed((tmp_path,)) == ()


def test_the_user_directory_shadows_a_system_entry_of_the_same_id(
    tmp_path: Path,
) -> None:
    """XDG precedence: the first directory to define an id wins."""
    user, system = tmp_path / "user", tmp_path / "system"
    write(user, "firefox.desktop", entry(Name="Mine", Exec="/mine %u"))
    write(system, "firefox.desktop", entry(Name="Packaged", Exec="/packaged %u"))
    (found,) = browsers.installed((user, system))
    assert found.name == "Mine"
    assert found.argv == ("/mine", "%u")


def test_the_list_is_sorted_by_name(tmp_path: Path) -> None:
    """Stable order, so the dropdown does not reshuffle between runs.

    Directory iteration order is not guaranteed, and a control whose entries
    move is one a user cannot build muscle memory for.
    """
    write(tmp_path, "z.desktop", entry(Name="Alpha"))
    write(tmp_path, "a.desktop", entry(Name="Zulu"))
    assert [b.name for b in browsers.installed((tmp_path,))] == ["Alpha", "Zulu"]


def test_entry_dirs_puts_the_user_directory_first(monkeypatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", "/home/x/.local/share")
    monkeypatch.setenv("XDG_DATA_DIRS", "/usr/local/share:/usr/share")
    assert browsers.entry_dirs() == (
        Path("/home/x/.local/share/applications"),
        Path("/usr/local/share/applications"),
        Path("/usr/share/applications"),
    )


# --------------------------------------------------------------------------
# Containment — one hostile entry costs its own row and nothing else
# --------------------------------------------------------------------------


def test_a_hostile_entry_costs_only_its_own_row(tmp_path: Path) -> None:
    """Every refusal shape in one fixture, beside a good entry that survives.

    This is the class `scanner.py` met four times — a non-`OSError` escaping a
    per-item loop and taking the whole batch with it. Asserted as a class here
    rather than one guard at a time, because that is what the four earlier
    fixes each failed to do.
    """
    write(tmp_path, "good.desktop", entry(Name="Good"))
    (tmp_path / "bad-utf8.desktop").write_bytes(b"[Desktop Entry]\nName=\xff\xfe\n")
    (tmp_path / "huge.desktop").write_bytes(b"#" * (MAX_FILE_BYTES + 1))
    (tmp_path / "a-directory.desktop").mkdir()

    assert [b.name for b in browsers.installed((tmp_path,))] == ["Good"]


def test_an_unreadable_directory_costs_only_that_directory(tmp_path: Path) -> None:
    """`Path.glob` raises `EACCES` on a directory you cannot enter (3.13).

    The same `pathlib` behaviour that returned 0 of 20 projects from the
    scanner. One bad directory must cost its own browsers, not the list.
    """
    good, blocked = tmp_path / "good", tmp_path / "blocked"
    write(good, "b.desktop", entry(Name="Good"))
    blocked.mkdir()
    blocked.chmod(0o000)
    try:
        if os.access(blocked, os.R_OK):  # pragma: no cover - running as root
            pytest.skip("cannot make a directory unreadable as this user")
        assert [b.name for b in browsers.installed((blocked, good))] == ["Good"]
    finally:
        blocked.chmod(0o700)


def test_a_missing_directory_is_not_an_error(tmp_path: Path) -> None:
    assert browsers.installed((tmp_path / "nope",)) == ()


# --------------------------------------------------------------------------
# by_id
# --------------------------------------------------------------------------


def test_by_id_finds_the_chosen_browser(tmp_path: Path) -> None:
    found = (Browser("firefox.desktop", "Firefox", ("/bin/ff", "%u")),)
    assert browsers.by_id(found, "firefox.desktop") is found[0]


@pytest.mark.parametrize("entry_id", [None, "uninstalled.desktop"])
def test_by_id_is_none_for_no_choice_and_for_a_stale_one(entry_id: str | None) -> None:
    """A stale id reads as "no choice", never as an error.

    The browser may simply be uninstalled today. Falling back to the desktop
    default keeps Open working, and the stored id stays in the file so
    reinstalling the browser restores the choice.
    """
    found = (Browser("firefox.desktop", "Firefox", ("/bin/ff", "%u")),)
    assert browsers.by_id(found, entry_id) is None


# --------------------------------------------------------------------------
# open_url
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url", ["file:///etc/passwd", "--version", "javascript:alert(1)", "ftp://x/"]
)
def test_open_url_refuses_anything_that_is_not_an_http_url(
    url: str, monkeypatch
) -> None:
    """The URL becomes `argv`, so it must not be able to read as an option.

    A refusal rather than an escape: `mainwindow.project_url` builds the only
    URL that reaches here, and there is no legitimate caller with a third
    scheme.
    """
    spawned: list = []
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **kw: spawned.append(argv))
    browser = Browser("b.desktop", "B", ("/bin/b", "%u"))

    with pytest.raises(BrowserError, match="refusing to open"):
        browsers.open_url(browser, url)

    # The assertion that matters. `pytest.raises(BrowserError)` alone passed
    # against a build with NO scheme check at all: the spawn of a nonexistent
    # binary fails and raises the same type, so the test was green for a reason
    # unrelated to the rule. The rule is that a bad URL never reaches a process.
    assert spawned == []


def test_open_url_spawns_the_expanded_argv_detached_and_never_a_shell(
    monkeypatch,
) -> None:
    seen: dict[str, object] = {}

    def fake_popen(argv, **kwargs):
        seen["argv"] = argv
        seen["kwargs"] = kwargs
        return None

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    browsers.open_url(
        Browser("b.desktop", "B", ("/bin/b", "--new-tab", "%u")),
        "http://localhost:3000/",
    )

    assert seen["argv"] == ("/bin/b", "--new-tab", "http://localhost:3000/")
    kwargs = seen["kwargs"]
    assert kwargs["start_new_session"] is True, (
        "a browser sharing our process group is a candidate for a signal "
        "supervisor.stop() aims at a server"
    )
    assert "shell" not in kwargs


def test_open_url_reports_a_launch_failure_rather_than_raising_oserror(
    monkeypatch,
) -> None:
    def fake_popen(argv, **kwargs):
        raise FileNotFoundError(2, "No such file or directory")

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    with pytest.raises(BrowserError, match="could not launch"):
        browsers.open_url(Browser("b.desktop", "B", ("/gone", "%u")), "http://x/")
