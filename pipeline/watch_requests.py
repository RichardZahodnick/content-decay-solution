#!/usr/bin/env python3
"""Run the content-decay check for each site the OpenClaw agent asks for.

Usage:  python3 watch_requests.py             watch the agent's request folder until stopped with Control-C
        python3 watch_requests.py --yes       also pull rankings for new sites without asking here first
        python3 watch_requests.py --once      handle the requests that are waiting, then stop
        python3 watch_requests.py --no-open   don't open the report in the browser when a run finishes

HOW THE AGENT ASKS. The agent runs in a sandbox with no internet and no way to run programs on this Mac. It can only
write files in its own workspace. To ask for a check it writes a small text file holding a site name:
    ~/openclaw/workspaces/assistant/decay/requests/<site>.txt
This program, running on the Mac, sees the file, checks that it holds one plain domain name and nothing else,
runs run_site.py for it, and writes the result where the agent can read it:
    ~/openclaw/workspaces/assistant/decay/results/<site>.md
The only thing that crosses from the sandbox to the Mac is a domain name that has passed the same check
run_site.py uses. No OpenClaw setting has to be loosened for this.

When a run finishes, this program opens the report in the browser. The agent cannot do that: the report is
outside its workspace, and a small model tends to shorten the path into a link that goes nowhere. So the agent's
result file holds only the lines to pass on, and no file path at all.

SAFETY
  - The request file is treated as untrusted: only its first line is read, it must be a regular file under 1,000
    bytes, and its content is never run.
  - A site with no ranking data on disk costs money to pull. Without --yes, this program asks in this Terminal
    window before pulling. run_site.py's spending limits apply either way.
  - At most MAX_RUNS_PER_HOUR runs an hour, and a site that finished in the last REPEAT_MINUTES is not run again;
    the agent is pointed at the result it already has.
  - Results are written without following links, and only inside the decay folder, so nothing placed in the
    workspace can redirect a write to somewhere else on the Mac.
"""
import datetime, os, pathlib, re, subprocess, sys, time

import run_site

WORKSPACE = pathlib.Path(os.environ.get("OPENCLAW_WORKSPACE") or pathlib.Path.home() / "openclaw" / "workspaces" / "assistant")
MAX_REQUEST_BYTES = 1000
MAX_RUNS_PER_HOUR = 6
REPEAT_MINUTES = 10
POLL_SECONDS = 5
FOLDERS = ("requests", "results", "done")


def box(workspace=WORKSPACE):
    return workspace / "decay"


def prepare(workspace=WORKSPACE):
    """Create the folders. Refuse to work if any of them is a link to somewhere else."""
    root = box(workspace)
    for folder in (root, *(root / name for name in FOLDERS)):
        if folder.is_symlink():
            raise run_site.Refused(f"{folder} is a link, not a real folder. Remove it and start again.")
        folder.mkdir(parents=True, exist_ok=True)
    return root


def safe_write(root, folder, name, text):
    """Write root/folder/name without following links. name must be a plain file name."""
    if "/" in name or name.startswith(".") or not name:
        raise ValueError(f"not a plain file name: {name!r}")
    parent = root / folder
    if parent.is_symlink() or root.is_symlink() or parent.resolve() != root.resolve() / folder:
        raise run_site.Refused(f"{parent} is not the real folder it should be; nothing was written.")
    path = parent / name
    if path.is_symlink():
        path.unlink()
    handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(handle, "w") as out:
        out.write(text)
    return path


def read_request(path):
    """The site name a request file asks for. Raises Refused with a reason a person can read."""
    if path.is_symlink() or not path.is_file():
        raise run_site.Refused("the request is not an ordinary file")
    if path.stat().st_size > MAX_REQUEST_BYTES:
        raise run_site.Refused("the request file is too long; it should hold one site name")
    lines = [line.strip() for line in path.read_text(errors="replace").splitlines() if line.strip()]
    if len(lines) != 1:
        raise run_site.Refused("the request should hold exactly one line: the site name")
    return run_site.clean_domain(lines[0])


def plain_name(text):
    """A file name that is safe whatever the request was called."""
    return re.sub(r"[^a-z0-9.-]+", "-", text.lower()).strip("-.")[:80] or "request"


RULE = "-" * 10


def reply_block(site, summary, opened=True):
    """What the agent should pass on: the Result and Top of the work queue sections of the run summary, between two
    lines of dashes. It holds no file path, because a small model shortens a path into a dead link."""
    lines, keep = [], False
    for line in summary.splitlines():
        if line.startswith("## "):
            keep = line[3:].strip() in ("Result", "Top of the work queue")
            if keep:
                lines += ["", line[3:].strip() + ":"]
            continue
        if keep and line.strip():
            lines.append(line)
    body = "\n".join(lines).strip() or "The run produced no result section."
    where = ("The full report has opened in the browser on the Mac." if opened else
             "The full report is saved on the Mac. Ask for the check again to have it opened in the browser.")
    return ("Give the user the text between the two lines of dashes, copied word for word. Do not reword it, shorten it or add to it. "
            "Do not mention any file name or link.\n\n"
            f"{RULE}\n\nContent decay check for {site}\n\n{body}\n\n{where}\n\n{RULE}\n")      # blank lines: dashes right under text make a heading


def mac_open(path):
    """Open a file in its default app (the report in the browser). Does nothing off macOS."""
    if sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=False)


def note(status, detail=""):
    return f"Status: {status}\n" + (f"\n{detail}\n" if detail else "")


def handle(path, workspace=WORKSPACE, data_dir=None, auto_pull=False, history=None, ask=input, run=None, now=None, say=print, open_report=None):
    """Deal with one request file. Returns (site or None, status)."""
    root, history = box(workspace), history if history is not None else []
    data_dir = data_dir or run_site.DATA_DIR
    run, now = run or run_site.run, now or time.time()
    stamp = datetime.datetime.fromtimestamp(now).strftime("%H:%M")
    done_name = f"{datetime.datetime.fromtimestamp(now).strftime('%Y%m%d-%H%M%S')}-{plain_name(path.stem)}.txt"

    def finish(site, status, text):
        safe_write(root, "results", f"{site or plain_name(path.stem)}.md", text)
        if not path.is_symlink() and path.exists():
            os.replace(path, root / "done" / done_name)
        say(f"  {stamp}  {site or path.name}: {status}")
        return site, status

    def show(site):
        report = data_dir / site / "report.html"
        if open_report and report.exists():
            open_report(report)

    try:
        site = read_request(path)
    except run_site.Refused as stop:
        return finish(None, "rejected", note("rejected", f"{stop}"))
    recent = [t for s, t in history if s == site and now - t < REPEAT_MINUTES * 60]
    if recent and (data_dir / site / "run_summary.md").exists():
        summary = (data_dir / site / "run_summary.md").read_text()
        show(site)
        return finish(site, "already done", note(f"finished (this site was checked {int((now - recent[-1]) / 60)} minutes ago; this is that result)",
                                                 reply_block(site, summary, bool(open_report))))
    if len([t for _, t in history if now - t < 3600]) >= MAX_RUNS_PER_HOUR:
        return finish(site, "too many runs", note("not started", f"{MAX_RUNS_PER_HOUR} checks have already run in the last hour. Try again later."))
    new_site = not (data_dir / site / "keywords.csv").exists()
    if new_site and not auto_pull:
        safe_write(root, "results", f"{site}.md", note("waiting for approval", "This site has no ranking data yet, and pulling it costs money. "
                                                         "A person has to approve it in the Terminal window where watch_requests.py is running."))
        answer = ask(f"  {site} has no ranking data yet. Pull it from DataForSEO (about $0.25 to $1.55)? [y/N] ")
        if answer.strip().lower() not in ("y", "yes"):
            return finish(site, "declined", note("not started", "The person at the Terminal declined to pull ranking data for this site."))
    safe_write(root, "results", f"{site}.md", note(f"running since {stamp}", "The check takes about 3 to 6 minutes. Read this file again later."))
    say(f"  {stamp}  {site}: running ...")
    try:
        status = run(site, data_dir, say=lambda *_: None)
    except run_site.Refused as stop:
        return finish(site, "not started", note("not started", str(stop)))
    history.append((site, now))
    summary = pathlib.Path(status["summary_file"]).read_text()
    if not status["ok"]:
        return finish(site, "stopped", note("stopped before the end", summary))
    show(site)
    return finish(site, "finished", note("finished", reply_block(site, summary, bool(open_report))))


def waiting(workspace=WORKSPACE):
    folder = box(workspace) / "requests"
    files = [p for p in folder.iterdir() if p.suffix == ".txt" and not p.name.startswith(".") and not p.is_symlink() and p.is_file()]
    return sorted(files, key=lambda p: p.stat().st_mtime)             # links and folders are ignored, never opened


if __name__ == "__main__":
    flags = set(sys.argv[1:])
    if flags - {"--yes", "--once", "--no-open"}:
        sys.exit(__doc__)
    try:
        root = prepare()
    except run_site.Refused as stop:
        sys.exit(str(stop))
    history, stuck = [], set()
    print(f"Watching {run_site.shown(root / 'requests')} for requests from the agent. Stop with Control-C.")
    if "--yes" in flags:
        print("New sites will be pulled without asking here. Spending limits still apply.")
    try:
        while True:
            for request in waiting():
                if request.name in stuck:
                    continue
                handle(request, auto_pull="--yes" in flags, history=history, open_report=None if "--no-open" in flags else mac_open)
                if request.exists():                   # could not be moved to done/: don't handle it again and again
                    stuck.add(request.name)
                    print(f"  {request.name} could not be moved out of the requests folder; ignoring it from now on.")
            if "--once" in flags:
                break
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        print("\nStopped.")
