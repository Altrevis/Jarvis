# Skill spaces

One folder per IT domain. Each one is the toolbox of one **specialist agent**
of the agent team (`actions/agents.py`, `core/orchestrator.py`): when a mission
gives a task to the `cyber` specialist, that agent runs in a folder whose
`.claude/skills/` holds the skills of `skill_spaces/cyber/` — and nothing else.

| Space | Specialist |
|---|---|
| `programming` | Writing, fixing, refactoring and explaining code in any language |
| `web` | Websites and web apps, front-end, back-end, APIs |
| `mobile` | iOS and Android, native and cross-platform |
| `desktop` | Windows, macOS and Linux applications, packaging |
| `cyber` | Defensive security: secure code review, threat models, hardening |
| `network` | Addressing, VLANs, routing, DNS/DHCP, firewalls, VPN, Wi-Fi |
| `infra` | Servers, virtualisation, backups, Terraform / Ansible |
| `cloud` | AWS, Azure, Google Cloud architecture, IAM, costs |
| `devops` | CI/CD, Docker, Kubernetes, releases, observability |
| `database` | Data models, SQL / NoSQL schemas, indexes, migrations |
| `data` | Data analysis and engineering, cleaning, charts, reports |
| `ml` | Machine-learning models, evaluation, MLOps |
| `ai-agents` | LLM agents, tools, prompts, RAG, MCP, Claude skills |
| `design` | UI/UX, design systems, accessibility (WCAG) |
| `qa` | Test strategy, unit / integration / end-to-end tests |
| `architecture` | Architecture decisions (ADR), C4, patterns |

`python -m core.spaces` lists them with their skills;
`python -m core.spaces --check` validates every space and skill.

## Why spaces, and not one skills folder

Claude Code lists every skill it can see to the model on every turn of an
agent run. Put sixteen domains of skills in `workspace/.claude/skills/` and
every `ask_claude` task pays for all of them, in tokens — and a security agent
choosing among Flutter and Terraform skills chooses worse. A space is copied
only into the run folder of the specialist that needs it, like the packs in
`skill_packs/` are copied only into the project that uses them.

## Layout

```
skill_spaces/<id>/SPACE.md                 the specialist
skill_spaces/<id>/<skill>/SKILL.md         a skill it works with
skill_spaces/<id>/<skill>/<script>.py      tools the skill runs (optional)
```

`SPACE.md` front matter:

| Key | Meaning |
|---|---|
| `name` | The id — exactly the folder name, lower case and dashes |
| `title` | Shown in lists and in the agent's prompt |
| `description` | What the specialist covers. **The lead plans from it**: it decides which specialist gets which task |
| `keywords` | Comma-separated, English and French. Routes a delegation to the right space locally, without spending a token (accents and case are ignored, a longer phrase beats a shorter one) |
| `model` | `sonnet` (default), `haiku`, `opus`, or `agent` for the `claude_model_agent` tier |
| `bash` | Shell presets the specialist gets on top of the base allowlist — see below |

The body is the specialist's **role**: scope, what it hands over to the other
spaces, how it works, its quality bar and its safety lines. It is appended to
the agent's system prompt. The generic rules (nobody can answer questions,
keep token use low, no shell loops, the final `STEP:` line) are added by the
orchestrator and do not belong here.

A skill is a standard Claude skill: `name` (the folder name) and a
`description` that says what it does and when to use it, with English and
French trigger words. Its scripts are run by the specialist as
`python3 .claude/skills/<skill>/<script>.py`.

## Shell presets

A specialist runs unattended, so its Bash access is an allowlist. The base list
is `core/claude.AGENT_BASH` (python, node, npx, `npm install`, `pip install`,
`ls`, `mkdir`, `cat`, `head`, `file`, `pdftoppm`, `soffice`). A space adds
**presets by name**; the commands behind each name are defined in
`core/spaces.BASH_PRESETS`, not in `SPACE.md`, so no file in a space — or a
skill downloaded into one — can widen them.

| Preset | Adds |
|---|---|
| `git-read` | `git -C <folder> status`, `diff`, `log`, `show`, `branch`, `rev-parse` |
| `git-local` | `git init <folder>`, `git -C <folder> add`, `commit` |
| `node-dev` | `npm ci`, `npm i`, `npm run`, `npm test`, `npm init` |
| `python-dev` | `pytest`, `ruff check`, `ruff format --check`, `mypy` |
| `docker-read` | `docker compose config`, `docker version`, `docker images`, `docker ps` |
| `net-read` | `ip addr`/`route`/`link`, `ping -c`, `dig`, `nslookup`, `host`, `traceroute`, `tracepath`, `ipconfig` |
| `audit` | `npm audit` (report only), `pip-audit`, `bandit`, `gitleaks detect` |

Git goes through `git -C <folder>`: a specialist's current folder is its run
folder, and Claude Code refuses `cd <folder> && git …`. Because the `*` in
`git -C * log *` matches any text, `core/spaces.GIT_DENY` refuses, for every
specialist, the subcommands that discard or send work (`push`, `pull`, `fetch`,
`reset`, `clean`, `checkout`, `restore`, `rebase`, `stash`, `rm`, `config`,
`commit --amend`, branch deletion…) and the options that inject config (`-c`) or
write files (`--output`). Deny rules win over allow rules — measured, not
assumed.

Nothing that deletes, deploys, pushes, applies infrastructure or scans another
machine is on any of them. Specialists write the files and list those commands
for the user in their handoff.

## Adding a skill

By voice, through `manage_skills` with a `space`:

- *« Crée un skill Terraform pour l'espace infra : … »* — Claude writes it into
  `skill_spaces/infra/`
- *« Cherche un skill de pentest pour l'espace cyber »*, then *« installe-le »*
  — from the public catalogue into the space
- *« Liste les skills de l'espace réseau »*, *« supprime le skill X de l'espace data »*

Or by hand: a folder with a `SKILL.md`, then `python -m core.spaces --check`.
The next task of that specialist sees it; no restart.

## Adding a space

Create `skill_spaces/<id>/SPACE.md` with the front matter above and a role,
add at least one skill, run `python -m core.spaces --check`, and restart the
app: the `agents` tool lists the spaces it was started with, and the lead
plans with every space it finds.

## Configuration

In `config/api_keys.json`, all optional:

| Key | Default | |
|---|---|---|
| `agents_models` | — | Model per space, e.g. `{"cyber": "opus"}` |
| `agents_model` | — | Model for every specialist |
| `agents_planner_model` | the smart tier (`claude_model_smart`, Opus) | The lead |
| `agents_review_model` | `sonnet` | The reviewer |
| `agents_review` | `true` | Review missions of two tasks or more |
| `agents_max_tasks` | `5` | Most tasks a plan may have (1–8) |
| `agents_parallel` | `2` | Specialists of one mission at once |
| `agents_task_minutes` | `20` | Time limit of one specialist run |
| `claude_agent_slots` | `3` | Claude agent runs alive at once, for the whole app (restart to apply) |
