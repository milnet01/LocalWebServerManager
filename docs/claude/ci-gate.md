# The local CI gate — detail

Moved word for word out of `CLAUDE.md` on 2026-10-01, to keep the
always-loaded instructions under Claude Code's size limit.
`CLAUDE.md` § Before pushing and § Build and test points here and still holds the rules.

**The hook gates the commits being pushed, not your working tree**
(LWSM-1160). It checks each pushed tip out into a detached worktree and
runs the gate there, so uncommitted work neither hides a failure nor
invents one. Your tree is not touched, and the extra checkout costs
about five seconds.

The hook decides docs-only **by the paths in the push, never by the
commit subject**, and `scripts/`, `.github/`, `src/` and `tests/` are
never exempt — a change to the checker must run the check.
`tests/test_ci_contract.py` asserts that, because an exemption that
grew to cover `scripts/` would let an edit to the gate skip the gate.

**Some markdown takes the FULL gate, and that was missed until
2026-08-19**: `CLAUDE.md`, `README.md`, every file under
`docs/standards/` and the two design documents that name theme ids
(`design-look-and-feel.md`, `design-accessibility.md`) are asserted
against by `tests/test_docs.py`, and
`CONTRIBUTING.md` by `tests/test_ci_contract.py`, so an edit to one can
redden the suite. They never take the docs mode. The cost of learning this was a red CI run on
`5f1891f`, a markdown-only push that skipped the gate on the strength of
its paths and was caught by GitHub instead. **The carve-out list is
imported from `test_docs.ASSERTED`, never copied** — a standard added
there alone would otherwise leave the contract test green while the file
it governs skips the suite. And the test **runs** `docs_only()` rather
than reading it: its predecessor scanned the case arms as strings, which
can say which patterns are present but never which arm a path lands in.
Every assertion in it held while the escape went through.

**The hook runs the gate under CI's environment, not a developer's** — it
sets `LWSM_REQUIRE_ALL_TOOLS=1`, so a check that did not run and a tool at
a version CI does not install both REFUSE the push instead of warning about
it. Added 2026-08-21 (LWSM-1159), and it is the same argument the hook
already made for `--fast`: what runs here has to be what runs on GitHub.
Measured with actionlint off PATH, the identical tree exited **0** through
the hook and **1** under the workflow — so the push went out and GitHub
failed it, which is precisely the split the hook exists to close. Running
`./scripts/local-ci.sh` **by hand** is unaffected and stays lenient.

**The tool VERSIONS are pinned in `scripts/ci-tools.env`, which both
the workflow and the gate read**, and the gate reports any tool whose
version differs from the pin as **TOOL DRIFT** — a warning locally, and
fatal under `LWSM_REQUIRE_ALL_TOOLS=1`, where a mismatch means CI did
not install what it promised. **Pinning the steps was never enough; a
gate is its tools.** Found the hard way on 2026-08-18: local shellcheck
0.11.0 passed `scripts/*.sh` while the runner's apt shipped 0.9, which
reports SC2015 on `command -v` guards that 0.11 accepts — so five
consecutive pushes went red against a green local run. To bump a tool,
change the version there; the workflow interpolates it and
`tests/test_ci_contract.py` fails if the two ever part.

**`uv` is the exception to the interpolation**, because `setup-uv` takes
its version as a `uses:` input and a `uses:` input cannot read a shell
variable. The workflow repeats the literal and the contract test asserts
the two are equal — the test is doing the job interpolation does for the
other three.

There is no compile step. `scripts/local-ci.sh` runs, in order: the
tool-version check against `scripts/ci-tools.env`, `uv sync --locked`, the
version lockstep check, `ruff check`, `ruff format --check`,
`python -m compileall src tests` (the syntax gate), `pyright` over
`src/` at its standard level (LWSM-1066), an
entry-point resolution check, `pytest`, `shellcheck`, and
`actionlint` + `yamllint`. A check whose tool is missing is
reported as an explicit **SKIP**, never folded into the pass —
**each tool is tracked separately**, because sharing one flag
between `actionlint` and `yamllint` made a missing `actionlint`
report a clean pass (reproduced and fixed 2026-08-06).

**`yamllint` runs `--strict` against `.yamllint.yml`, not `-d relaxed`**
(2026-08-18). Two changes, and both were needed to make CI *fully*
clean rather than merely passing. The config raises `line-length` to
**100**, because 80 is the wrong limit for a file whose central security
practice is pinning every action to a 40-character commit SHA — 63
characters of a pinned `uses:` line are spoken for before the action is
named, and `actions/checkout` fit inside 80 by a single character while
`astral-sh/setup-uv` did not. Neither the SHA nor the trailing version
comment can be shortened: the comment must stay trailing or dependabot
stops rewriting it. And `--strict` makes a warning exit non-zero,
because yamllint's default is to report one and exit 0 — which is how an
82-character line sat in the CI annotations of runs everyone read as
green. **Turn a warning class fatal only once its count is zero**; the
alternative is a gate people learn to push past.

`-c` and `-d` are mutually exclusive, so reverting to `-d relaxed`
silently discards the config *and* the raised limit together.

In CI, a SKIP is **fatal**: the workflow sets
`LWSM_REQUIRE_ALL_TOOLS=1`, so the machine that is supposed to
hold every tool cannot report green on a degraded run. **The
`pre-push` hook sets it too** (LWSM-1159) — a local run standing in
for CI has to answer the question CI will ask. What stays lenient is
running the script **by hand**: a missing linter should not stop you
testing your own change, and that is the only case the asymmetry was
ever for.

`.python-version` is committed, so a developer's machine and the
runner resolve the **same** interpreter. `requires-python` is only
a floor, and `filterwarnings = ["error"]` would turn any
divergence into a red build that does not reproduce locally.
