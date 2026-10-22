# Skill packs

Claude skills that ship with the app but are **not** installed in
`workspace/.claude/skills/`. Every `ask_claude` task lists every skill it can
see there, so a pack only one feature uses would be paid for, in tokens, on
every task that never touches it. A pack here is copied into the folder of the
thing that needs it instead.

## replica/

The Replica pack by Jake Schincariol — eleven skills that take an app from
recon to launch, each reading what the previous one wrote in `replica/`.

- Source: https://github.com/Jakeschincariol/replica-skill
- Commit: `77c9436fb3d18c3d58169efb8caf4fe906b0dc51` (2026-10-03)
- Licence: MIT, see `replica/LICENSE`
- Left out: the repository's `tests/` and `.claude-plugin/` manifest

Used by `actions/project.py`: each project gets its own copy in
`<project>/.claude/skills/`. The bundled Python tools are standard-library only
and make no network calls. To update, copy the `replica-*` folders from a newer
commit over these and change the commit above.
