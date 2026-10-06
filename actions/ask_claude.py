"""
ask_claude — the voice hands the thinking to Claude.

Gemini Live hears and speaks; Claude reasons. Two shapes, because a voice
request arrives in two:

    answer   "explique-moi la relativité restreinte simplement"
             -> one Claude call (a few seconds), the answer comes back to the
                voice model to say. A long answer — code, a plan, an essay —
                goes on the display and the voice gives the gist.
    task     "compare ces trois offres et fais-moi un tableau dans un fichier"
             -> Claude Code as an agent, in the background: files, code, web,
                and every skill in workspace/.claude/skills. The assistant
                says so when it is done.

Runs on the user's Claude Code subscription (core/claude.py).
"""
from __future__ import annotations

from pathlib import Path

from core import claude, jobs
from core.user_dirs import jarvis_documents_dir

# Past this, an answer is something to read rather than something to hear.
_SHOW_OVER_CHARS = 700
# An agent task that has not finished in this long is not going to.
_TASK_TIMEOUT = 15 * 60


def _assistant_name() -> str:
    try:
        from memory.config_manager import get_assistant_name
        return get_assistant_name()
    except Exception:
        return "JARVIS"


def _answer_system(language: str) -> str:
    lang = f" Write in {language}." if language else ""
    return (
        f"You are the reasoning engine behind {_assistant_name()}, a voice "
        f"assistant. A voice model reads your answer and tells the user, so lead "
        f"with the answer itself, then only what supports it. Plain prose: no "
        f"markdown headings, no tables, no preamble, no closing offer. Use a code "
        f"block only when the user asked for code. Be concrete and exact.{lang}"
    )


def _agent_system(language: str, out_dir: Path) -> str:
    lang = f" Write any text meant for the user in {language}." if language else ""
    return (
        f"\n\nYou are working for {_assistant_name()}, a voice assistant, on a "
        f"task the user asked for out loud. Nobody can answer questions while you "
        f"work: make reasonable choices and finish the job. Use a skill from "
        f".claude/skills when one fits. Save every deliverable the user should "
        f"keep in {out_dir} (scratch files can stay in the current directory). "
        f"Your final message is read by the voice model: at most five sentences "
        f"saying what you did and what you found, then the full path of each "
        f"file you created, one per line.{lang}"
    )


def _dirs_for(files) -> list[str]:
    out = []
    for f in files or ():
        p = Path(str(f)).expanduser()
        d = p if p.is_dir() else p.parent
        if d.exists() and str(d) not in out:
            out.append(str(d))
    return out


def ask_claude(parameters: dict, player=None) -> str:
    p = parameters or {}
    request = str(p.get("request") or "").strip()
    if not request:
        return "No request given. Pass the full question or task in 'request'."
    mode = str(p.get("mode") or "answer").lower().strip()
    language = str(p.get("language") or "").strip()
    files = [str(f) for f in (p.get("files") or []) if str(f).strip()]

    if claude.engine() != "claude":
        return ("Claude is switched off: ⚙ SETUP → CLAUDE is set to Gemini only. "
                "Answer the user yourself.")
    if not claude.binary():
        return ("Claude Code is not installed on this computer, so Claude is not "
                "available. Tell the user to install it from claude.com/claude-code "
                "and sign in from ⚙ SETUP → CLAUDE.")
    resting = claude.cooling()
    if resting:
        return f"Claude is unavailable right now ({resting}). Tell the user briefly."

    if mode == "task":
        out_dir = jarvis_documents_dir("claude")
        label = f"CLAUDE — {' '.join(request.split())[:48]}"

        def work(progress) -> str:
            def on_event(ev):
                act = claude.tool_activity(ev)
                if act:
                    progress(act)
            prompt = request
            if files:
                prompt += "\n\nFiles to work with:\n" + "\n".join(files)
            res = claude.agent(prompt, append_system=_agent_system(language, out_dir),
                               add_dirs=[str(out_dir)] + _dirs_for(files),
                               timeout=_TASK_TIMEOUT,
                               on_event=on_event)
            if player is not None and hasattr(player, "show_content"):
                player.show_content(label, res.text)
            return (f"Claude finished the task. Its report (also on the display): "
                    f"{res.text[:1200]}\nTell the user in one or two sentences what "
                    f"was done and where the result is.")

        jobs.start(player, label, work)
        return ("status=started_in_background. Claude is working on it; you will be "
                "told when it is done. Say one short sentence that it has started, "
                "then carry on with the conversation.")

    prompt = request
    if files:
        contents = []
        for f in files[:5]:
            try:
                text = Path(f).expanduser().read_text(encoding="utf-8", errors="replace")
                contents.append(f"--- {f} ---\n{text[:20000]}")
            except Exception:
                pass
        if contents:
            prompt += "\n\n" + "\n\n".join(contents)
    try:
        answer = claude.ask(prompt, claude.SMART, system=_answer_system(language),
                            web=bool(p.get("web")), timeout=150 if p.get("web") else 90)
    except claude.ClaudeError as e:
        return f"Claude could not answer: {e}"

    if len(answer) > _SHOW_OVER_CHARS or "```" in answer:
        if player is not None and hasattr(player, "show_content"):
            player.show_content(f"CLAUDE — {' '.join(request.split())[:40]}", answer)
        return (f"Claude's full answer is now on the display. Give the user its gist "
                f"in two or three sentences, without reading it out:\n{answer[:3000]}")
    return answer


TOOL = {
    "name": "ask_claude",
    "description": (
        "Hands thinking to Claude, a stronger reasoning model. Use mode 'answer' "
        "for anything that needs real thought or knowledge: explanations, advice, "
        "analysis, maths, writing or rewriting text, code, plans, comparisons, "
        "summaries of text the user gives. Use mode 'task' for multi-step work "
        "that produces something — research with several sources, writing files, "
        "data processing, using one of the installed skills; it runs in the "
        "background and you are told when it finishes. Not for small talk, and "
        "not when a dedicated tool exists (documents: create_document, videos: "
        "create_motion_video, skills: manage_skills, live news: web_search)."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "request": {"type": "STRING",
                        "description": "The complete question or task with all the context Claude needs, as the user meant it"},
            "mode": {"type": "STRING",
                     "description": "answer (default, a few seconds) | task (background agent with files, code, web and skills)"},
            "language": {"type": "STRING",
                         "description": "Language the user is speaking, e.g. 'French' — Claude writes in it"},
            "files": {"type": "ARRAY", "items": {"type": "STRING"},
                      "description": "Full paths of files the request is about"},
            "web": {"type": "BOOLEAN",
                    "description": "answer mode only: let Claude search the web first (adds ~20 s)"},
        },
        "required": ["request"],
    },
    "handler": ask_claude,
}
