---
name: ci-cd-pipeline
description: >-
  Sets up or reviews build-test-deploy: branching model, CI stages from lint
  to deploy with caching and fail-fast, GitHub Actions and GitLab CI with
  pinned actions, least-privilege permissions and OIDC, multi-stage non-root
  Dockerfiles, Docker Compose for local dev, Kubernetes manifests with probes
  and limits, SemVer releases, rolling, blue-green and canary deployments with
  rollback, and SLO-based alerting. Use for CI/CD, Docker, Kubernetes or a
  release process. Se déclenche sur : pipeline CI/CD, intégration continue,
  GitHub Actions, Dockerfile, conteneuriser, Kubernetes, déploiement, mise en
  production.
---

# ci-cd-pipeline
Produces pipeline files (`.github/workflows/*.yml` or `.gitlab-ci.yml`),
container files (`Dockerfile`, `.dockerignore`, `compose.yaml`), optional
Kubernetes manifests, and `devops-notes.md`. The agent writes and validates;
the user pushes and deploys.

## Before you start
| Input | Where | If missing |
|---|---|---|
| Language, build and test commands | `package.json` scripts, `pyproject.toml`, `Makefile`, README, existing CI | infer from the manifest; record it |
| CI platform | `.github/`, `.gitlab-ci.yml`, task | GitHub Actions |
| Runtime and target | task, cloud or infra handoffs | container image to a registry, deployed by the user |
| Environments | task | `staging` and `production`, production behind an approval |
| Secrets needed | code (`os.environ`, `process.env`), `.env.example` | list them; never invent values |

## Method
1. **Branching**: trunk-based or GitHub flow — short-lived branches, pull
   requests with review and green CI, protected `main`, tags for releases.
2. **Stages**, fail-fast, in order: lint and format check → unit tests →
   build → security scans (dependency audit, image scan) → package (image,
   artefact) → deploy staging → (approval) → deploy production.
3. **Write the CI file** for the platform (template below): triggers on pull
   request and on `main`, dependency cache keyed on the lock file, a matrix only
   where several versions really matter, `concurrency` to cancel superseded
   runs, timeouts on jobs.
4. **Container**: multi-stage Dockerfile (checklist), `.dockerignore`, and
   `compose.yaml` for local development (app plus its database, volumes,
   health checks, env from a `.env` that is git-ignored).
5. **Kubernetes** (only if asked or already used): Deployment, Service,
   ConfigMap, Secret reference, probes, resources, rolling update; Helm or
   Kustomize when several environments differ.
6. **Release**: SemVer tags (`v1.4.2`), a changelog per release, the image
   tagged with the version and the commit SHA.
7. **Deployment strategy** with a rollback (table below).
8. **Observability**: structured logs, the four golden signals (latency,
   traffic, errors, saturation), an SLO with its error budget, alerts on
   symptoms.
9. **Validate**: parse YAML with python3 (PyYAML if it imports; otherwise
   read carefully), `docker compose config` when Docker is installed, check
   that every script, path and secret name the pipeline uses exists. Record
   what was validated and what was not.
10. **Write** `devops-notes.md`.

## Checklists

### GitHub Actions
- `permissions:` at workflow or job level, `contents: read` by default; add
  only what a job needs (`id-token: write` for OIDC, `packages: write` to
  push an image).
- Third-party actions pinned to a full commit SHA (with the version in a
  comment) or at least a version tag; official `actions/*` by version tag.
- Secrets via `${{ secrets.NAME }}`; cloud access by OIDC federation instead of
  long-lived keys; never echo secrets.
- `pull_request` for untrusted code; never run untrusted pull-request code with
  secrets (`pull_request_target` only with care).
- `concurrency: { group: ${{ github.workflow }}-${{ github.ref }}, cancel-in-progress: true }`.
- Production job with `environment: production` (protection rules and
  reviewers set by the user).

### GitLab CI
- `stages:`, `rules:` instead of `only/except`, `cache:` keyed on the lock
  file, `needs:` for a DAG, protected variables for secrets, `environment:`
  with manual `when: manual` for production.

### Dockerfile
| Rule | Why |
|---|---|
| Multi-stage: build stage, then a small runtime stage | no compilers or sources in the final image |
| Base image pinned (version tag, ideally digest), slim or distroless | reproducible, smaller attack surface |
| Copy dependency manifests and install before copying the source | layer cache survives code changes |
| `USER` non-root (create it) | a compromise does not get root in the container |
| `.dockerignore`: `.git`, `node_modules`, `.env`, build output | smaller context, no secrets copied |
| No secrets in `ENV`, `ARG` or `COPY`; build secrets via BuildKit secret mounts | layers are readable by anyone with the image |
| `HEALTHCHECK` (or Kubernetes probes) | the platform knows when to restart |
| One process; exec form `CMD ["app"]`; handle SIGTERM | clean shutdowns and signals |

### Kubernetes workload
`resources.requests` and `limits`; `readinessProbe` and `livenessProbe`
(and `startupProbe` for slow starts); image tag = version or SHA; config in a
ConfigMap, secrets from a Secret or an external secret operator;
`securityContext` with `runAsNonRoot: true` and `readOnlyRootFilesystem` where
possible; `RollingUpdate` with `maxUnavailable` and `maxSurge`; a
PodDisruptionBudget for replicated services.

### Deployment strategies
| Strategy | Use | Rollback |
|---|---|---|
| Rolling | default for stateless services | redeploy the previous image tag (`kubectl rollout undo` by the user) |
| Blue-green | instant switch, easy rollback | point traffic back to blue |
| Canary | risky changes, real-traffic check | route the canary weight back to 0 |
| Database changes | expand → deploy → contract, never a breaking migration in the same release | the expand step is backward compatible |

## Deliverable
Files in the target folder (or the shared work folder), plus
`devops-notes.md` in the shared work folder (translate the headings into the
user's language):

```markdown
# DevOps notes — <project>
## Summary
## Pipeline
| Trigger | Stage | Command | Fails when |
## Containers
## Deployment and rollback
## Secrets and settings the user creates
| Name | Where (repo secret, environment, vault) | Used by |
## Observability
| Signal | SLI | Target (SLO) | Alert | Owner | First action |
## Validation done
## Commands for the user
## Decisions
## Next steps
```

Minimal GitHub Actions shape to adapt:

```yaml
name: ci
on: { pull_request: {}, push: { branches: [main] } }
permissions: { contents: read }
concurrency: { group: "${{ github.workflow }}-${{ github.ref }}", cancel-in-progress: true }
jobs:
  test:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version-file: .nvmrc, cache: npm }
      - run: npm ci
      - run: npm run lint
      - run: npm test
```
Use the action versions current when you write it (check with WebSearch if
unsure) and the project's own commands.

## Pitfalls
- A pipeline calling `npm run test` when the project has no such script.
- `:latest` images or unpinned third-party actions.
- Secrets printed in logs (`set -x`, `echo $TOKEN`) or baked into images.
- `pull_request_target` checking out and running untrusted code with secrets.
- Caching `node_modules` instead of the package manager's cache keyed on the
  lock file.
- A Dockerfile that copies the whole source before installing dependencies.
- Liveness probes that hit the database: one slow query restarts every pod.
- Deploying a breaking schema change and the code in one step.
- Writing "the pipeline passes" when it has never run: say "not run yet".
