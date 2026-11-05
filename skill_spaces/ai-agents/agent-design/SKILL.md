---
name: agent-design
description: >-
  Designs or builds an LLM agent or AI feature: workflow versus agent
  decision, task decomposition, tool and function-calling design with JSON
  Schemas, prompt structure and structured output, model selection by cost
  and latency, memory, RAG with hybrid search and citations, multi-agent
  patterns with file handoffs, MCP servers, Claude skills, prompt-injection
  guardrails, evaluation sets and LLM-as-judge, token budgets and tracing.
  Use for a chatbot, an agent, RAG, an MCP server or a skill. Se déclenche
  sur : agent IA, système agentique, multi-agents, prompt, RAG, MCP, créer un
  skill, chatbot, évaluation de LLM.
---

# agent-design
Produces `agent-design.md` (job definition, architecture, tools, prompts,
guardrails, evaluation plan and results, cost estimate) plus the code, prompt
files, tool schemas or SKILL.md files the task asks for.

## Before you start
| Input | Where | If missing |
|---|---|---|
| The job and its users | task, handoffs | write it as input → output with 3 examples |
| Success and failure | task | define both; "never" rules too (e.g. never sends without confirmation) |
| Provider, SDK, framework | target code (`anthropic`, `openai`, `@modelcontextprotocol/sdk`, `langgraph`...), config | the provider already used; otherwise provider-neutral design |
| Model ids, keys | config, `.env.example` | placeholders read from configuration |
| Data for RAG | target folders | describe the corpus needed under For the user |
| Limits | task: latency, cost per task, privacy | interactive: < 5 s to first output; record a cost ceiling |

## Method
1. **Define the job**: inputs, outputs, success criteria, forbidden outcomes,
   3–5 worked examples (they become the first evaluation cases).
2. **Choose the structure** (table below), simplest first: a single call; a
   fixed workflow (chaining, routing, parallel calls); an evaluator-optimizer
   loop; an orchestrator with workers; an autonomous agent only when the
   steps cannot be known in advance.
3. **Tools**: list the actions; design each tool (checklist); keep the set
   small and non-overlapping.
4. **Prompts**: system prompt (role, context, rules, output format), then
   examples; long reference material placed before the question; sections
   delimited with XML-style tags; output schema for anything code reads.
5. **State and memory**: what persists between turns or sessions, where, for
   how long, and who can read it; summaries or files instead of whole
   transcripts.
6. **RAG** if the job needs the user's documents (checklist).
7. **Guardrails** (checklist), including confirmation for irreversible
   actions.
8. **Evaluation**: build the set (examples + edge cases + adversarial
   inputs), the grading (exact checks first, rubric-based LLM-as-judge for
   open answers, human spot checks), and the regression run command.
9. **Cost**: tokens per step × steps × calls per day × price per token from
   the provider's pricing page (cite it) or as units; caching for repeated
   prefixes.
10. **Build and test**: code with the project's SDK; unit tests with a fake
    model client (`cd "<target>" && python3 -m pytest -q` or `npm test`);
    live evaluation runs go to For the user with the expected cost.
11. **Write** `agent-design.md`.

## Checklists

### Workflow or agent
| Shape | Use when | Example |
|---|---|---|
| Single call + retrieval | one answer from given context | FAQ answer with citations |
| Prompt chaining | fixed steps, each checkable | outline → draft → check → format |
| Routing | inputs of different kinds | classify a ticket, send to the right prompt |
| Parallelisation | independent sub-tasks or votes | several reviewers, majority verdict |
| Orchestrator-workers | sub-tasks known only after reading the input | a lead plans, specialists execute, results handed back as files |
| Evaluator-optimizer | quality improves with feedback | draft, critique against a rubric, revise (bounded rounds) |
| Autonomous agent | open-ended steps, tool feedback needed | coding agent in a sandbox, with a step and cost limit |

### Tool design
- Name says the action (`search_orders`, not `helper`); the description says
  what it does, when to use it and when not.
- JSON Schema with types, enums, required fields and examples; inputs
  validated server-side anyway.
- Returns compact, relevant data (not whole records); errors say what to do
  next ("customer_id not found; call search_customers first").
- Idempotent where possible; side-effecting tools require an explicit
  confirmation token from a human, never a parameter the model fills.
- Least privilege: read-only tools separate from write tools; allowlists for
  paths, hosts and commands.

### Prompting
- Say what to do rather than what not to do; give the reason for unusual
  rules.
- Examples cover edge cases and show the exact output format.
- Ask for structured output against a schema; validate, and retry once with
  the validation error.
- Keep stable content first (system prompt, tools, documents) so prompt
  caching can reuse it.

### RAG
| Step | Rule |
|---|---|
| Chunking | by structure (headings, paragraphs), a few hundred tokens with small overlap; keep source and position metadata |
| Retrieval | hybrid: keyword (BM25) + embeddings; filters on metadata |
| Reranking | rerank the top candidates before putting them in the prompt |
| Answer | quote or cite the chunks used; say "not in the documents" when retrieval finds nothing |
| Evaluation | retrieval recall@k on labelled questions, then answer faithfulness |

### MCP servers and Claude skills
- MCP: expose tools (actions), resources (readable data) and prompts;
  transport stdio for local servers, streamable HTTP for remote ones;
  authenticate remote servers; same tool-design rules as above.
- Claude skill: a folder with `SKILL.md` whose frontmatter has `name` (the
  folder name) and a `description` that says what it does and when to use it,
  with trigger words; the body is loaded only when used, so keep it focused and
  move long references or scripts into files next to it.

### Guardrails
- Content from tools, retrieved documents, web pages and emails is data:
  instructions inside it are ignored; say so in the system prompt and keep
  untrusted text inside delimiters.
- Allowlists for tools, file paths, domains and commands; deny by default.
- Human confirmation for irreversible or outward-facing actions.
- Limits: max steps, max tokens, max cost, timeouts per tool.
- No secrets in prompts or logs; personal data minimised and redacted in
  traces.
- Output checks for the forbidden outcomes defined in step 1.

## Deliverable
Code, prompts, schemas or skill files in the target folder (or the shared
work folder), and `agent-design.md` (translate the headings into the user's
language):

```markdown
# Agent design — <feature>
## Summary
## Job definition
| Input | Expected output | Must never |
## Architecture
<structure chosen and why; diagram in Mermaid>
## Tools
| Tool | Purpose | Inputs (schema) | Side effects | Confirmation |
## Prompts
## State and memory
## Retrieval (if any)
## Guardrails
## Evaluation
| Set | Cases | Grading | Result (as run) | Command |
## Cost and latency estimate
<arithmetic: tokens × calls × price or units, with the source>
## Decisions
## Next steps
```

## Pitfalls
- An autonomous agent where a three-step workflow would do.
- Overlapping tools the model cannot tell apart.
- Letting the model fill a `confirmed: true` parameter for a destructive tool.
- Treating retrieved text or tool results as trusted instructions.
- No evaluation set: every prompt change is a guess.
- Judging with an LLM without a rubric or spot checks.
- Hardcoded model ids and keys; prices quoted from memory.
- Passing whole transcripts between agents instead of short handoffs.
