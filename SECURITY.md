# Security Policy

LifeRescue handles emergency-incident data and runs an AI engineering workforce, so security rules are strict. Controls below are the ones **stated in the baseline documents** (docs 16 s17, 18 s12, 19 steps 3 and 14). Where a control is listed as "target", it is **not yet enforced** in this repository.

## Reporting a vulnerability

- **Do not open a public issue** for a vulnerability or an exposed secret.
- Report privately to the repository owner, Ojas Sharma (GitHub: [@ojas005](https://github.com/ojas005)), using GitHub's private security advisory feature if enabled for the repository, otherwise by direct private message.
- A dedicated security contact address and response-time targets are **TBD** (not defined in the baseline).
- Private vulnerability reporting on GitHub was **not enabled** when this file was created (API returned 404 on 2026-10-03).

## Secrets rules

- No secrets, API keys, tokens, private keys, or credentials in the repository, issues, PRs, logs, prompts, or Confluence/Jira.
- `.env` files, key files and Terraform state are git-ignored (see `.gitignore`).
- No secrets in the database (doc 18 s6); secrets live in a secret manager (product TBD, doc 16 s17 / doc 18 s12).
- Agents receive short-lived, least-privilege credentials, never in prompts (doc 16 s17).
- If a secret is committed: treat it as compromised, **revoke/rotate it first**, then clean up. History rewriting is a separate, human-approved action.
- CI runs a secret scan (gitleaks) on every pull request and push to `main`. It must not be disabled or weakened.

## Controls from the baseline

| Control | Source | Status in this repository |
|---|---|---|
| Pull requests required; no direct writes to `main` | doc 19 step 3, doc 16 s9 | Process rule only. Branch protection/rulesets could not be read or enabled via API (HTTP 403, plan limitation) |
| Required status checks, force-push and deletion disabled | doc 19 step 3 | Not enforced (same limitation) |
| Secret scanning (platform) | doc 19 step 3 | Disabled in repository settings at creation time |
| Dependency alerts (platform) | doc 19 step 3 | Disabled in repository settings at creation time |
| Secret scan in CI | doc 19 step 9 | Active (`.github/workflows/ci.yml`, gitleaks) |
| Dependency scanning | doc 16 s17, doc 18 s12 | Active, report-only (`dependency-audit` in `.github/workflows/ci.yml`: pip-audit / npm audit over tracked lock files; findings never block yet) |
| SBOM, container scanning | doc 16 s17, doc 18 s12 | Not implemented |
| Signed commits where practical | doc 19 step 3 | Not enforced |
| Least-privilege CI token (`contents: read`) | engineering practice | Active |
| Independent review, no self-merge | doc 16 s9, s11 | Process rule (CODEOWNERS present) |
| OAuth/OIDC, RBAC/ABAC, encryption in transit and at rest, network segmentation, WAF, rate limits, audit logs, prompt-injection defenses, tool allowlists | doc 18 s12 | Product architecture targets; nothing implemented yet |
| Immutable audit logs, tool allowlists, network egress restrictions, signed artifacts where practical | doc 16 s17 | Targets; nothing implemented yet |

## Security-sensitive changes need human approval

Authentication/authorization changes, security-policy changes, model/tool-permission changes, sensitive-data policy changes, destructive migrations, production deployment, external payment authority, irreversible external actions, safety-critical workflow changes, and major-version releases always need explicit human approval (doc 16 s15 plus owner-supplied additions).

## Supported versions

There are no releases yet. Supported-version policy is **TBD**.
