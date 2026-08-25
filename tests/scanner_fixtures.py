"""The detection regression corpus — one tree, one expectation per project.

`docs/design.md § Detection accuracy is a test suite, not an opinion` makes this
the corpus every future mis-detection is added to, so it lives here as data
rather than inline in a test body (`docs/specs/LWSM-1006-scanner-detection.md`
§ 7).

**Each expectation is derived from what the fixture holds, never from what the
real project does.** The real `project-d` runs on Flask's 5000; this fixture's
hop target imports no framework, so the expectation here is *unknown*. Copying
the real port instead would produce a corpus that disagrees with the rules it
exists to lock.

`testing.md § T1` forbids reading the real projects, so this tree is only ever
as true as the day someone last checked it against them — recorded in the spec's
§ 11 as one of its four `nothing` rows.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from lwsm.scanner import LauncherKind, PortRule


@dataclass(frozen=True)
class FixtureProject:
    """One candidate directory, plus what the rules must make of it."""

    name: str
    files: dict[str, str]
    executable: tuple[str, ...] = ()
    unit: str | None = None
    kind: LauncherKind | None = None
    argv: tuple[str, ...] = ()
    port: int | None = None
    rule: PortRule | None = None
    source: str | None = None
    why: str = ""


CORPUS: tuple[FixtureProject, ...] = (
    FixtureProject(
        name="project-a",
        # The `serve.mjs` is a decoy declaring a DIFFERENT port: without it the
        # corpus passes against an implementation that ignores the unit and
        # reads the directory (INV-17).
        files={"serve.mjs": "const PORT = 9999\n"},
        unit="project-a.service",
        kind=LauncherKind.SYSTEMD,
        argv=(),
        port=4321,
        rule=PortRule.ASSIGNMENT,
        source="the project-a.service unit",
        why="a bound unit whose Environment= carries the port",
    ),
    FixtureProject(
        name="project-b",
        files={"serve.py": "PORT = 8765\n"},
        kind=LauncherKind.PYTHON,
        argv=("python3", "serve.py"),
        port=8765,
        rule=PortRule.ASSIGNMENT,
        source="serve.py",
        why="serve.py with a port assignment",
    ),
    FixtureProject(
        name="project-c",
        files={"server.py": "DEFAULT_PORT = 4322\n"},
        kind=LauncherKind.PYTHON,
        argv=("python3", "server.py"),
        port=4322,
        rule=PortRule.ASSIGNMENT,
        source="server.py",
        why="server.py with a port assignment; serve.py is absent",
    ),
    FixtureProject(
        name="project-d",
        files={
            "start.sh": "#!/bin/sh\nexec python3 launcher.py\n",
            # Imports neither Flask nor Django, so rule 3 reaches no evidence
            # and the honest answer is *unknown*. See the module docstring.
            "launcher.py": '"""Reads its port from a saved setting."""\n'
            "import json\n\nSETTINGS = json\n",
        },
        executable=("start.sh",),
        kind=LauncherKind.SHELL,
        argv=("./start.sh",),
        why="start.sh hopping to a .py that declares no port and no framework",
    ),
    FixtureProject(
        name="project-e",
        files={
            "run.sh": "#!/bin/sh\nexec python3 launcher.py\n",
            "launcher.py": "from config import PORT\n\nprint(PORT)\n",
            "config.py": "PORT = 8123\n",
        },
        executable=("run.sh",),
        kind=LauncherKind.SHELL,
        argv=("./run.sh",),
        port=8123,
        rule=PortRule.ASSIGNMENT,
        source="config.py",
        why="a wrapper runs the program and the program imports its port",
    ),
    FixtureProject(
        name="project-e-deep",
        files={
            "run.sh": "#!/bin/sh\nexec python3 launcher.py\n",
            "launcher.py": "from mid import PORT\n\nprint(PORT)\n",
            "mid.py": "from config import PORT\n",
            "config.py": "PORT = 8123\n",
        },
        executable=("run.sh",),
        kind=LauncherKind.SHELL,
        argv=("./run.sh",),
        why="the walk is still bounded — one invocation and one import, no more",
    ),
    FixtureProject(
        name="project-f",
        files={
            "start.sh": '#!/bin/sh\nPORT=8080\nexec python3 -m http.server "$PORT"\n',
        },
        executable=("start.sh",),
        kind=LauncherKind.SHELL,
        argv=("./start.sh",),
        port=8080,
        rule=PortRule.EXPLICIT,
        source="start.sh",
        why="start.sh declaring its port directly",
    ),
    FixtureProject(
        name="project-g",
        files={"run.sh": "#!/bin/sh\nPORT=${PORT:-8080}\nexec node serve.mjs\n"},
        executable=("run.sh",),
        kind=LauncherKind.SHELL,
        argv=("./run.sh",),
        port=8080,
        rule=PortRule.EXPLICIT,
        source="run.sh",
        why="rule 1's first alternative, the ${PORT:-N} form",
    ),
    FixtureProject(
        name="project-p-variable-interpreter",
        # LWSM-1183, found in the wild rather than imagined: the launcher picks
        # its interpreter at runtime, so the LAUNCH line names no keyword and the
        # last line that did was the assignment above it.
        files={
            "start.sh": "#!/bin/sh\nPYTHON=python3\n$PYTHON app.py\n",
            "app.py": "PORT = 8123\n",
        },
        executable=("start.sh",),
        kind=LauncherKind.SHELL,
        argv=("./start.sh",),
        port=8123,
        rule=PortRule.ASSIGNMENT,
        source="app.py",
        why="a variable in command position is still an invocation",
    ),
    FixtureProject(
        name="project-h-flask",
        files={"serve.py": "import flask\n\napp = flask.Flask(__name__)\n"},
        kind=LauncherKind.PYTHON,
        argv=("python3", "serve.py"),
        port=5000,
        rule=PortRule.FRAMEWORK_DEFAULT,
        source="Flask",
        why="a framework and no port anywhere — the only exercise rule 3 gets",
    ),
    FixtureProject(
        name="project-i-node-modules",
        files={
            # No port of its own, so the hop IS resolved and § 4.5 constraint 3
            # is the only thing refusing it. A start.sh declaring its own port
            # would end the search file-major before the hop was ever reached,
            # leaving constraint 3 unobservable (INV-20).
            "start.sh": "#!/bin/sh\nexec python3 node_modules/pkg/serve.py\n",
            "node_modules/pkg/serve.py": "PORT = 7777\n",
        },
        executable=("start.sh",),
        kind=LauncherKind.SHELL,
        argv=("./start.sh",),
        why="the hop target sits under node_modules, so it is never opened",
    ),
    FixtureProject(
        name="project-j-deep",
        files={
            "start.sh": "#!/bin/sh\nexec python3 a/b/c/d.py\n",
            "a/b/c/d.py": "PORT = 7778\n",
        },
        executable=("start.sh",),
        kind=LauncherKind.SHELL,
        argv=("./start.sh",),
        why="the hop target is four components down, past the depth bound",
    ),
    FixtureProject(
        name="project-k-vitest",
        files={
            "package.json": '{"scripts": {"dev": "vitest"},'
            ' "devDependencies": {"vitest": "^2.0.0"}}\n'
        },
        kind=LauncherKind.NODE,
        argv=("npm", "run", "dev"),
        why="vitest is a test runner; `vite` is an exact key and this is not it",
    ),
    FixtureProject(
        name="project-o-vite-in-a-comment",
        # `#` genuinely is a comment in an npm script — the value is handed to
        # `sh` — and § 4.6 says the stripper is shared by both port rules **and
        # by rule 3's evidence scan**. The evidence test searched the raw value,
        # so a note about a future migration was read as a Vite project and
        # given 5173 (LWSM-1130).
        files={
            "package.json": '{"scripts":'
            ' {"dev": "node server.js # switch to vite later"}}\n'
        },
        kind=LauncherKind.NODE,
        argv=("npm", "run", "dev"),
        why="the only `vite` on the line is inside a comment, so there is no port",
    ),
    FixtureProject(
        name="project-m-vite",
        # The dependency pair is the point: `"get-port": "^7.0.0"` is a real npm
        # package, and on a line of its own it partitions at `:` into a key
        # satisfying KEY_IS_PORT through the hyphen, so rule 2 reads **7** from
        # it. § 4.4's scope — the rules see exactly one value, the chosen
        # `scripts` entry — is the only thing keeping it away from them, and
        # nothing held it (LWSM-1126).
        #
        # **Pretty-printed deliberately.** Minified, the whole document is one
        # line whose first `:` belongs to `"scripts"`, so rule 2 stops there and
        # the fixture cannot see a scan that widened. The Vite-positive `dev`
        # script is what makes the expectation 5173 rather than unknown — the
        # corpus had no Vite-positive package.json at all.
        files={
            "package.json": "{\n"
            '  "scripts": {"dev": "vite"},\n'
            '  "dependencies": {\n'
            '    "get-port": "^7.0.0"\n'
            "  }\n}\n"
        },
        kind=LauncherKind.NODE,
        argv=("npm", "run", "dev"),
        port=5173,
        rule=PortRule.FRAMEWORK_DEFAULT,
        source="Vite",
        why="the dependency block is out of scope, so `get-port` is not port 7",
    ),
    FixtureProject(
        name="project-n-unexecutable-launcher",
        # Rule 1 requires the execute bit (§ 4.4), and every other fixture that
        # plants a `start.sh` also chmods it — so the fall-through had no
        # coverage and the guard's own line never ran (LWSM-1127). Both files
        # declare a port, and they differ, so which rule fired is visible in the
        # result rather than merely inferable.
        files={
            "start.sh": "#!/bin/sh\nPORT=1111\nexec true\n",
            "package.json": '{"scripts": {"dev": "vite --port 2222"}}\n',
        },
        kind=LauncherKind.NODE,
        argv=("npm", "run", "dev"),
        port=2222,
        rule=PortRule.EXPLICIT,
        source="package.json",
        why="a start.sh without the execute bit falls through to rule 2",
    ),
    FixtureProject(
        name="project-l-flask-login",
        files={"serve.py": "import flask_login\n"},
        kind=LauncherKind.PYTHON,
        argv=("python3", "serve.py"),
        why="`import flask_login` contains `import flask`; the evidence is a word",
    ),
)


def build_tree(root: Path) -> Path:
    """Write `CORPUS` under `root` and return it."""
    for project in CORPUS:
        base = root / project.name
        base.mkdir()
        for relative, content in project.files.items():
            target = base / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        for relative in project.executable:
            (base / relative).chmod(0o755)
    return root


@dataclass
class FakeUnits:
    """A `SupportsUnitLookup` that touches no service manager (`testing.md § T1`).

    `properties()` is **total** over `names`, which is the Protocol's contract
    and not a convenience: a fake that omitted a key would hide the `KeyError`
    an incomplete real adapter raises — and a `KeyError` is not an `OSError`, so
    it escapes `scan()` and takes every project's row with it.
    """

    units: dict[str, dict[str, str]] = field(default_factory=dict)
    property_calls: list[str] = field(default_factory=list)
    name_calls: int = 0

    def unit_names(self, timeout: float) -> list[str]:
        self.name_calls += 1
        return list(self.units)

    def properties(
        self, unit: str, names: Sequence[str], timeout: float
    ) -> dict[str, str]:
        self.property_calls.append(unit)
        held = self.units.get(unit, {})
        return {name: held.get(name, "") for name in names}


def corpus_units(root: Path) -> FakeUnits:
    """The unit lookup the corpus expects: one unit, bound to `project-a`.

    The `Environment` value carries **no `Environment=` prefix**, because that
    is what `properties()` returns and what § 4.4 step 3 measures the rules
    against. A fake carrying the prefix reproduces the shape that matches
    *neither* port rule, so a correct implementation would go red.
    """
    return FakeUnits(
        units={
            "project-a.service": {
                "LoadState": "loaded",
                "FragmentPath": str(root / "project-a" / "project-a.service"),
                "Environment": "APP_PORT=4321 REFRESH=24",
            }
        }
    )
