# Security Policy

LocalWebServerManager starts other projects' launch scripts, stops the
processes they create, and reads files in directories it did not write.
A bug in any of that can run code the user never agreed to, or stop a
program that was not ours. Security reports are welcome and are treated
as the highest-priority class of issue.

## Reporting a vulnerability

**Report privately, through GitHub — do not open a public issue.**

Use the repository's **[Report a vulnerability][advisory]** form
(Security tab → *Report a vulnerability*). It is private: only the
maintainer sees it, and it stays hidden until a fix ships.

[advisory]: https://github.com/milnet01/LocalWebServerManager/security/advisories/new

**No email address is published, deliberately.** `docs/standards/documentation.md`
§ 2.4 asks for a contact email; this project answers it with the private
advisory form instead. The project has one maintainer, and an address
published on a public repository is scraped within days, which buries
real reports in spam. The form asks for a GitHub account in return. If
you have a report and cannot use it, open a public issue saying only
*"I have a security report and no GitHub account"*, with **no details**,
and a private channel will be arranged from there.

No GPG key is published either: the advisory form is already a private
channel, so a key would add a step without adding protection.

### What to include

Whatever you have. A report is useful long before it is complete.
Most valuable, roughly in order:

- What an attacker gets — a launcher run without the confirmation, a
  process signalled that the app did not start, a file read or written
  outside the project, code run in the desktop session.
- The steps to reproduce, and the version or commit you saw it on.
- Your desktop session (Wayland or X11) and how you installed the app.

### What happens next

This is a single-maintainer project, so these are honest expectations
rather than a service-level agreement:

| Stage | Expect |
|---|---|
| Acknowledgement | within **7 days** |
| An assessment — is it real, how bad, is it in scope | within **14 days** |
| A fix, for a confirmed issue | in the **next release** |
| Public disclosure | when the fix ships, via a GitHub Security Advisory and a `CHANGELOG.md` entry |

Credit is given by name in the advisory and the changelog unless you
ask otherwise.

## Supported versions

**Only the latest release is supported.** There are no maintenance
branches and no backports. Until the first release is tagged, that
means the `main` branch.

## Scope

The trust model is in the decision records, and they are the authority:
[ADR-0003](docs/decisions/0003-launch-via-project-scripts.md) for
launching (the confirmation before a discovered launcher runs, and what
the child process inherits) and
[ADR-0004](docs/decisions/0004-runtime-truth-from-probing.md) for
stopping servers the app did not start.

**In scope** — for example:

- A launcher that runs without the confirmation, or whose confirmation
  survives a change to its command or its contents.
- A signal reaching a process the app did not start and the user did
  not choose to stop.
- A crafted project directory that makes the scanner read outside it,
  hang, or crash the app.
- Text from a scanned project that changes what a dialog appears to
  say.

**Out of scope** — an attacker who already controls the user's account:
anything able to write to the app's own configuration directory can run
code as the user without the app's help.
