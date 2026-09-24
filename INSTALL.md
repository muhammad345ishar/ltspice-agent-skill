# Installing and using the ltspice skill

`ltspice` is packaged as an **Agent Skill** — a folder with a [`SKILL.md`](SKILL.md)
manifest (YAML `name`/`description` + instructions) alongside [`scripts/`](scripts)
and [`reference/`](reference). Anthropic published Agent Skills as an open standard
in December 2025, and the same folder now works across a growing list of AI tools.

Two things make this skill portable:

1. The `SKILL.md` format is understood natively by an increasing number of agents
   (Claude, ChatGPT, Gemini CLI, GitHub Copilot, Cursor, and more).
2. The scripts are **pure Python standard library, no dependencies**. So even an AI
   that has never heard of `SKILL.md` can use the skill as long as it can run Python
   and read files — see [Any other AI](#any-other-ai-universal-fallback).

Repo: https://github.com/muhammad345ishar/ltspice-agent-skill

> **Skim `scripts/` before you install — from this repo or any other.** A skill can
> run code on your behalf. These scripts are stdlib-only and make no network calls,
> but you should confirm that yourself rather than take a stranger's word for it.

> **In chat, the AI can read and edit LTspice files but cannot run real simulations**
> (there is no LTspice binary in a chat sandbox). Everything else — summarising a
> schematic, listing/changing component values, adding directives, reading `.raw`
> and `.log` output you upload — works.

Jump to your platform:

- [Claude](#claude) — desktop app or claude.ai
- [ChatGPT / OpenAI](#chatgpt--openai)
- [Google Gemini](#google-gemini)
- [Coding agents](#coding-agents) — Copilot, Cursor, Windsurf, Codex CLI
- [Any other AI](#any-other-ai-universal-fallback) — the universal fallback

---

## Claude

Do this on desktop (Claude desktop app, or claude.ai in a desktop browser).

### One-time setup

1. Go to **Settings > Capabilities** and turn **ON**:
   - Code execution and file creation
   - Allow network egress (lets Claude reach GitHub)
2. Go to **Customize > Skills** and turn **ON** `skill-creator`.

### Install

3. Open a **new chat** and paste this prompt:

   ```text
   /skill-creator Install the "ltspice" skill from this GitHub repo:
   https://github.com/muhammad345ishar/ltspice-agent-skill
   ```

4. Wait while Claude clones the repo, builds the folder, runs the self-tests and
   packages the skill.
5. Click **Save skill** on the `ltspice.skill` file card.
6. Go to **Customize > Skills** and check that `ltspice` is listed with its toggle **ON**.
7. Test it: attach a `.asc` file and ask *"What does this circuit do? List the component values."*
8. (Optional) Turn **Allow network egress** back off. The skill doesn't need it to run.

### Using it

- **Desktop app or desktop browser:** type `/ltspice` in the chat box, then write your request.
- **Mobile app:** the `/` picker doesn't work there. Once the skill is installed, just ask
  in plain words: *"Use my ltspice skill to change R1 to 4.7k."*
- Claude also picks it up on its own when you attach `.asc`, `.raw` or `.log` files.

### If something goes wrong

- **No Skills section:** redo step 1.
- **`/skill-creator` doesn't show up:** redo step 2, or write *"use the skill-creator skill"*.
- **Can't reach GitHub:** turn on **Allow network egress**. If it still fails, download the
  repo and provide the `ltspice.skill` file (or the folder) manually.
- **Upload says name mismatch:** the folder must be named exactly `ltspice`.

**Claude Code (terminal / IDE):** clone the repo into `~/.claude/skills/ltspice`
(personal) or `.claude/skills/ltspice` (per-project), then run `/skills` to confirm
it's picked up.

```bash
git clone https://github.com/muhammad345ishar/ltspice-agent-skill.git ~/.claude/skills/ltspice
```

---

## ChatGPT / OpenAI

ChatGPT now supports **Skills** natively, and the OpenAI API/Codex support uploading
skill bundles. Because this skill runs Python, make sure code execution is available.

### ChatGPT (web / desktop app)

The most reliable route, since this skill depends on running its scripts:

1. Open **Skills** (in the sidebar / settings) and choose **Create**. You can "create
   with chat" and paste the contents of [`SKILL.md`](SKILL.md) as the instructions.
2. Attach the skill's files so ChatGPT can run them — upload the [`scripts/`](scripts)
   `.py` files (and, if you want the format docs, [`reference/`](reference)). A single
   `.zip` of the repo works too.
3. Save the skill. ChatGPT triggers it automatically when a task matches its
   description, or you can `@mention` it. Skills shared with you install from
   **Skills > Shared with me > ⋯ > Install**.

If your workspace doesn't expose Skills yet, the same thing works as a **custom GPT**
(paste `SKILL.md` into *Instructions*, upload `scripts/` as *Knowledge*, enable the
Code Interpreter capability) or in a plain chat with the code tool enabled (upload a
zip of the repo, paste `SKILL.md`, then ask your question).

### OpenAI API / Codex (developers)

- **API:** upload the skill bundle to `POST https://api.openai.com/v1/skills` — either
  a multipart directory or a `.zip` with a single top-level `ltspice/` folder — then
  attach it by `skill_id` to a hosted container (`container_auto`), or run it locally
  by supplying its `name`, `description` and `path`.
- **Codex CLI / sandbox:** place the skill folder where your Agents sandbox looks for
  capabilities and register the parent directory, or just point Codex at a checkout of
  the repo and tell it to follow `SKILL.md`.

```bash
git clone https://github.com/muhammad345ishar/ltspice-agent-skill.git ltspice
```

---

## Google Gemini

### Gemini CLI (recommended)

Gemini CLI implements the Agent Skills standard. Install straight from GitHub:

```bash
# global (all projects)
gemini skills install https://github.com/muhammad345ishar/ltspice-agent-skill.git --consent

# or scoped to the current project
gemini skills install https://github.com/muhammad345ishar/ltspice-agent-skill.git --scope workspace --consent
```

Then verify and manage it inside a session:

- `/skills list` — confirm `ltspice` is discovered (add `all` to include built-ins)
- `/skills enable ltspice` / `/skills disable ltspice`
- `/skills reload` — rediscover after a manual change

Skills also load automatically from these folders if you'd rather clone by hand:

- User (global): `~/.gemini/skills/ltspice/` (alias `~/.agents/skills/ltspice/`)
- Workspace (per-project): `.gemini/skills/ltspice/` (alias `.agents/skills/ltspice/`)

```bash
git clone https://github.com/muhammad345ishar/ltspice-agent-skill.git ~/.gemini/skills/ltspice
```

### Gemini app (consumer)

The consumer Gemini app's skill support is still expanding. The reliable route today
is to enable code execution, upload the [`scripts/`](scripts) files (or a repo zip),
and paste [`SKILL.md`](SKILL.md) as your opening instructions — the same
upload-and-instruct pattern as [Any other AI](#any-other-ai-universal-fallback).

---

## Coding agents

Copilot, Cursor, Windsurf, Codex CLI, and other agentic coding tools discover a skill
from a conventional folder in your repo or home directory. Clone the skill into the
matching path and the agent reads [`SKILL.md`](SKILL.md) on demand:

| Tool | Skill path |
|---|---|
| GitHub Copilot | `.github/skills/ltspice/` |
| Cursor | `.cursor/skills/ltspice/` |
| Windsurf | `.windsurf/skills/ltspice/` |
| Claude Code | `~/.claude/skills/ltspice/` or `.claude/skills/ltspice/` |
| Gemini CLI | `~/.gemini/skills/ltspice/` or `.gemini/skills/ltspice/` |

```bash
# example: install into a project for GitHub Copilot
git clone https://github.com/muhammad345ishar/ltspice-agent-skill.git .github/skills/ltspice
```

Cross-tool installers also work — e.g. `npx skills add muhammad345ishar/ltspice-agent-skill`
(skills.sh) or `skillkit install muhammad345ishar/ltspice-agent-skill` (SkillKit). Tools
that key off `AGENTS.md` instead of a skills folder (Codex CLI, some Cursor/Windsurf
setups) will still work if you reference `SKILL.md` from your `AGENTS.md`.

Whichever path you use, the folder must be named exactly `ltspice`, and the agent needs
permission to run Python in the repo.

---

## Any other AI (universal fallback)

The skill degrades gracefully to "a folder of CLI tools plus instructions." If your AI
can **run Python and read uploaded files**, you can use it anywhere:

1. Clone or download the repo.
2. Upload [`scripts/`](scripts) (and optionally [`reference/`](reference)), or a `.zip`
   of the whole repo.
3. Paste the contents of [`SKILL.md`](SKILL.md) as your first message so the model knows
   the routing rules and the encoding traps.
4. Attach your `.asc` / `.raw` / `.log` file and ask your question.

The scripts run standalone too — nothing about them is agent-specific:

```bash
python scripts/ltspice_asc.py summary path/to/circuit.asc
python scripts/ltspice_asc.py set-value path/to/circuit.asc R1 4.7k --output out.asc
python scripts/ltspice_raw.py summary path/to/circuit.raw --no-values
```

---

## Safety recap

- Agent Skills can execute code. **Read `scripts/` before installing** anything from a
  repo you don't control. This skill is stdlib-only and makes no network requests.
- In chat sandboxes there's no LTspice binary, so simulation and authoritative netlist
  generation don't run there — reading and editing files does. See
  [Known gaps](README.md#known-gaps) for what is and isn't verified.

## References

- [Agent Skills — Anthropic](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills)
- [Skills in ChatGPT — OpenAI Help Center](https://help.openai.com/en/articles/20001066-skills-in-chatgpt)
- [Agent Skills (Tools) — OpenAI API docs](https://developers.openai.com/api/docs/guides/tools-skills/)
- [Skills — Gemini CLI docs](https://github.com/google-gemini/gemini-cli/blob/main/docs/cli/skills.md)
