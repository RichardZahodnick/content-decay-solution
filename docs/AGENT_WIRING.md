# Running the check from an OpenClaw agent

The pipeline can be started from a chat with a local agent: "run the content decay check for example.com", and
a few minutes later, "what was the result for example.com?". This page explains how that works without giving
the agent any access it did not already have.

## The setup it runs in

- [OpenClaw](https://docs.openclaw.ai) 2026.9.7, with one agent, on one laptop.
- The chat model is a small local one (Qwen 3.5, 9B, through Ollama). Nothing is sent to a hosted model.
- Every session runs in a sandbox (`sandbox.mode: "all"`, a Docker container). The agent sees one folder, its
  workspace. It has no network access, and running commands is denied (`tools.exec.security: "deny"`).
- The pipeline, the ranking-data login and the data folder are all outside that workspace.

## The design

The agent does not run the pipeline. It leaves a request, and a program outside the sandbox does the work.

```
 chat ──> agent (sandboxed)                      watcher (outside the sandbox)
            │  writes  decay/requests/<site>.txt ──────>│ checks the request is one plain domain name
            │                                           │ runs the pipeline (run_site.py)
            │  reads   decay/results/<site>.md  <───────│ writes the result; opens the report in the browser
```

| Piece | File | What it does |
|---|---|---|
| Instructions | [`agent/AGENTS.md`](../agent/AGENTS.md), copied into the agent's workspace | Tells the agent it has no internet and cannot run commands; to start a check, write one file; to report, read one file and repeat a marked block word for word |
| Watcher | [`pipeline/watch_requests.py`](../pipeline/watch_requests.py) | Polls the request folder every 5 seconds, validates the request, runs the pipeline, writes the result, opens the report |
| Result file | `decay/results/<site>.md` in the workspace | First line is a status. When finished, it holds one block of text between two lines of dashes for the agent to repeat |

No OpenClaw setting was changed to make this work. The only thing that crosses from the sandbox to the host is
a domain name that has passed the same check the runner itself uses.

## Why the agent was not given command access

OpenClaw has a supported way to let a sandboxed agent run commands on the host: elevated mode. It was not used,
for three reasons found in the documentation and in testing:

- Elevated mode moves every command in the session to the host, not just one. The protection is then an
  allowlist and approval prompts, in front of a small model that builds tool calls unreliably.
- A command is put in the background after 10 seconds. A run takes minutes, so the agent would have to poll for
  it, which is more for a small model to get wrong.
- It needs the command policy loosened from "deny".

A file drop needs none of that, and the worst a confused or manipulated agent can do is ask for a check of a
site, which costs at most the per-run spending limit.

## Safety in the watcher

- **The request is untrusted.** It must be an ordinary file (links and folders are ignored), under 1,000 bytes,
  holding exactly one line. Its content is never run. The line must be a plain domain name.
- **Money needs a person.** A site with no ranking data on disk costs money to pull. The watcher asks in its own
  Terminal window before pulling, unless it was started with `--yes`. The runner's limits ($2.00 a run, $5.00 a
  day) apply either way.
- **Rate limits.** At most 6 runs an hour. A site that finished in the last 10 minutes is not run again; the
  agent is given the result it already has.
- **Writes cannot be redirected.** Results are written without following links and only inside the `decay`
  folder, so a link planted in the workspace cannot send a write elsewhere on the machine.
- **The agent never handles a path.** The result file holds no file name or link. The watcher opens the report
  itself, at a path built from the validated domain.

## What went wrong on the way

These are the useful part. Each one changed the design.

1. **A skill was not enough.** The steps were first written as a skill. The model never opened it. In two
   minutes it made 15 tool calls and 8 failed: it tried to run commands, asked for the host, and looked for a
   web-fetch tool. Every attempt was refused by the sandbox. The steps were moved into `AGENTS.md`, which is
   loaded at the start of every session, and it worked the first time.
2. **The model reworded the result.** The numbers were right, but it turned "4 keep both" into "4 keep their
   current positions in search results", which means something else. It added a total it had worked out itself,
   and it shortened the report's path into a link that went nowhere. Telling it to copy "word for word" did not
   stop this.
3. **What fixed it** was giving the model less to do. The result file was cut down to only the block to repeat.
   Every file path was removed from it. The summary was rewritten so each call is said in plain words and needs
   no interpreting. The watcher opens the report itself. On the next test the reply matched the file word for
   word.

What this suggests for small local models:

- Put must-follow instructions where the model always sees them, not in something it has to choose to open.
- Give literal tool names, paths and an example.
- Tell the model what it cannot do, so it stops trying.
- Hand it only the text to repeat, and nothing else it could summarize.
- Do in code whatever the model does not have to do.
- Do not let the model make decisions or produce numbers. Here it carries a request in and a result out.

## Running it

Four things need to be running: Docker (for the sandbox), the decision model, the OpenClaw gateway, and the
watcher.

```
cd pipeline
python3 watch_requests.py             # watch until stopped with Control-C
python3 watch_requests.py --yes       # also pull rankings for new sites without asking first
python3 watch_requests.py --once      # handle the requests that are waiting, then stop
python3 watch_requests.py --no-open   # don't open the report when a run finishes
```

The watcher looks for the agent's workspace at `~/openclaw/workspaces/assistant`; set `OPENCLAW_WORKSPACE` to
point somewhere else. Copy `agent/AGENTS.md` into that workspace and start a new session so the agent loads it.

The agent does not send a message when a run finishes. The report opening in the browser is the signal; then
ask the agent for the result.

## Not done

- Nothing checks the agent's reply against the result file. The word-for-word reply has been seen to work, not
  proven to always work. The report is the source of truth.
- The watcher is started by hand.
- Opening the report works on macOS only.
- This has been tested with one chat model, in the OpenClaw dashboard.
