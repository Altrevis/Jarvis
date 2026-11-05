---
name: infrastructure-as-code
description: >-
  Designs and automates servers and infrastructure as code: requirements and
  inventory, Linux/Windows baseline hardening (CIS Benchmarks), Terraform or
  OpenTofu modules with remote state, idempotent Ansible roles with vault,
  virtualisation and storage, 3-2-1 backups with restore tests, monitoring,
  and a runbook with dry runs, verification and rollback. It writes files only
  and never applies anything. Use for servers, IaC, Ansible, Terraform,
  backups or a runbook. Se déclenche sur : serveur, infrastructure, Terraform,
  Ansible, sauvegarde, durcissement Linux, Proxmox, supervision, procédure
  d'exploitation.
---

# infrastructure-as-code
Produces infrastructure files (Terraform/OpenTofu, Ansible, configuration
templates) and `infra-runbook.md`. The agent designs, writes and checks
syntax; the user applies, starting with a dry run.

## Before you start
| Input | Where | If missing |
|---|---|---|
| Server roles, load, users | task, handoffs (architecture, web) | one small VM per role; record sizing assumptions |
| Platform | task: on-premises (Proxmox, VMware, Hyper-V), cloud VM, bare metal | Linux VMs on a hypervisor, Ansible only |
| OS | task, existing inventory | current Debian stable or Ubuntu LTS, said without a version number unless given |
| Availability, RPO, RTO | task | RPO 24 h, RTO 4 h for a small team; record it |
| Existing IaC | target folders (`*.tf`, `inventory*`, `roles/`, `playbooks/`) | new layout below |
| Network | network handoff | placeholders `<SUBNET>`, `<GATEWAY>` |

## Method
1. **Inventory table**: host or group, role, OS, vCPU/RAM/disk, network,
   backup class, monitoring checks.
2. **Choose the tools**: Terraform/OpenTofu to create resources (VMs, cloud
   objects, DNS records) where a provider exists; Ansible to configure the
   operating system and services. Do not use Ansible to create what Terraform
   manages, or the reverse.
3. **Baseline** every host with the checklist below (one Ansible `baseline`
   role applied to all).
4. **Service roles**: one role per service (`nginx`, `postgres_client`,
   `node_exporter`...), with defaults, templates and handlers.
5. **Terraform layout**: `modules/<thing>/` (variables, main, outputs) and
   `envs/<env>/` calling them; remote backend with locking; versions pinned.
6. **Backups**: what, how often, where (3-2-1), encryption, retention, restore
   test procedure.
7. **Monitoring**: metrics (CPU, memory, disk, service up), logs shipped
   centrally, alerts with threshold, owner and action.
8. **Validate locally**: parse every YAML and JSON file with python3
   (`python3 -c "import json,sys; json.load(open(sys.argv[1]))" file.json`;
   YAML with a short script if PyYAML imports, else careful reading); check
   Jinja variables exist in defaults; re-read HCL for missing variables and
   outputs. Record what was and was not validated.
9. **Write** `infra-runbook.md`: prerequisites, dry run, apply, verify,
   rollback — the user runs every command.

## Checklists

### OS baseline (Linux)
| Area | Setting |
|---|---|
| Updates | unattended security updates (or a patch window); reboot policy |
| Accounts | named admin accounts, sudo group, no shared logins; root login disabled |
| SSH | `PasswordAuthentication no`, `PermitRootLogin no`, keys only, non-default port optional, `AllowGroups` |
| Firewall | default deny inbound (nftables/ufw/firewalld); only the role's ports |
| Time | chrony or systemd-timesyncd to the site NTP |
| Logs | journald persistent; forward to the central log server |
| Services | disable what the role does not use; no compilers on production if avoidable |
| Integrity | fail2ban or equivalent on exposed SSH; file permissions on secrets 0600 |
| Reference | CIS Benchmark for the distribution (Level 1 as the default target) |

Windows Server: named admin accounts with LAPS for local admin, Windows Update
policy, Defender on, firewall profiles on, RDP restricted to the admin network
with NLA, PowerShell logging.

### Terraform / OpenTofu
- `required_version` and `required_providers` with version constraints;
  commit the `.terraform.lock.hcl`, never `*.tfstate` or `.terraform/`.
- Remote state backend with locking; one state per environment.
- Variables typed, with `description` and `validation`; secrets marked
  `sensitive = true` and supplied by environment variables or a secret store.
- Tags or labels on every resource: owner, environment, cost centre.
- `terraform fmt`, `terraform validate` and `terraform plan` are user
  commands; the plan is reviewed before any apply.

### Ansible
- Inventory per environment; `group_vars/` and `host_vars/`; secrets in
  `ansible-vault` files, never in plain vars.
- Modules over `shell`/`command`; when unavoidable, `creates`, `removes` or
  `changed_when`.
- Handlers for restarts; `notify` only on real change.
- Roles have `defaults/main.yml` with every variable; templates validated
  (`validate:` for nginx, sshd, sudoers).
- User commands: `ansible-lint`, `ansible-playbook site.yml --check --diff`,
  then without `--check`.

### Backups
| Rule | Detail |
|---|---|
| 3-2-1 | 3 copies, 2 media, 1 off-site (and ideally 1 immutable or offline) |
| RAID and snapshots | not backups: they share the failure domain |
| Encryption | at rest and in transit; keys stored apart from the backups |
| Restore test | scheduled, with a measured restore time compared to the RTO |
| Databases | consistent dumps or the engine's backup tool, not file copies of a running database |

## Deliverable
Files in the target folder, or in `infra/` inside the shared work folder:

```
infra/
  terraform/modules/<name>/{main,variables,outputs}.tf
  terraform/envs/<env>/{main.tf,backend.tf,terraform.tfvars.example}
  ansible/{site.yml,inventory/<env>.ini,group_vars/all.yml,roles/<role>/...}
```

`infra-runbook.md` (translate the headings into the user's language):

```markdown
# Infrastructure runbook — <system>
## Summary
## Inventory
| Host / group | Role | OS | Size | Network | Backup | Monitoring |
## Prerequisites (for the user)
## Procedure
| # | Step | Command (run by the user) | Expected result | Rollback |
|---|---|---|---|---|
| 1 | Dry run | `ansible-playbook -i inventory/prod.ini site.yml --check --diff` | changes listed, none failed | — |
## Backups and restore test
## Monitoring and alerts
| Check | Threshold | Owner | Action |
## Validation done by the agent
## Decisions
## Next steps
```

## Pitfalls
- Shell tasks that report "changed" on every run, hiding real drift.
- Secrets in `group_vars`, `terraform.tfvars` or state committed to git.
- Unpinned providers or collections: the same code breaks next month.
- A backup plan with no restore test, or backups on the same host or RAID.
- Locking yourself out: SSH and firewall changes without a console fallback
  and a rollback step.
- Mixing environments in one state or one inventory.
- Writing "validated" for HCL or playbooks that only a tool the agent cannot
  run would validate: say "not run" and give the command.
