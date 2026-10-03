# LifeRescue Agent Registry

Status: DRAFT bootstrap registry, 2026-10-03 (Asia/Kolkata). Owner: Ojas Sharma. Documentation agent: LR 12. Sources: baseline docs 16-20 and the user's role definitions and permission baseline. Fields the baseline requires (doc 16 s4) but does not define are marked `TBD - not defined in baseline`; no numbers have been invented. Items marked *derived* are inferences from the baseline docs and need user confirmation.

## 1. Summary

| LR | Role | Platform agent id | Wave | Jira | Git | CI | Production |
|---|---|---|---|---|---|---|---|
| LR 01 | Orchestrator | `16e987ef-66bd-427a-be3c-f4489705b4fb` | Wave 1 | Read/Write limited to assignment, comments, links | Read | Read | None |
| LR 02 | Product Manager | `57717786-f5c2-456e-9c79-4172ad8b457c` | Wave 1 | Read/Write | Read | Read | None |
| LR 03 | Architect | `1197d5b3-9851-4b6c-ba49-7b290220938d` | Wave 1 | Read/Write limited to design tasks and comments | Read + branch/commit/PR for docs and ADRs only | Read | None |
| LR 04 | Backend Engineer | `f3bf2c12-2baa-452f-8a18-1668dbe675e8` | Wave 1 | Read/Write | Branch + commit + PR | Read results | None |
| LR 05 | Frontend Engineer | `c0ef1be6-6767-428b-ad65-5a7b924b1eab` | Deferred | Read/Write scoped to implementation-bot actions | Branch + commit + PR | Read results | None |
| LR 06 | Agent Engineer | `a3876af5-e951-4870-a911-c639a2e984d8` | Deferred | Read/Write scoped | Branch + commit + PR | Read results | None |
| LR 07 | QA / Evaluation | `c275d521-c638-449f-9f35-83d2d7ffd668` | Wave 1 | Read/Write scoped to findings and gate transitions | Read + test-code PRs | Read results | None |
| LR 08 | Security Engineer | `faa69525-3b4f-4dce-804a-88ac4c236930` | Wave 1 | Read/Write | Read | Read | None |
| LR 09 | Red Team | `3115eb58-1c22-4d1e-bd1f-9f188802f5c9` | Deferred | Read/Write findings only | Read | Read | None |
| LR 10 | SRE / DevOps | `5fa97934-58a9-40a2-b044-a7bca0d521ec` | Deferred | Read/Write scoped | Branch + commit + PR on infra/CI paths | Read + pipeline definition via PR | None |
| LR 11 | Code Reviewer | `9e35ca41-62aa-4edb-861d-54bc45626a51` | Deferred | Read + comment | Read + PR review | Read | None |
| LR 12 | Documentation | `d91dff24-1350-4652-98cb-e94b0de7bbb3` | Deferred | Read + comment | Branch + commit + PR on docs/ | Read | None |
| LR 13 | Release Manager | `47cf9085-ea3b-4fe7-8f4c-0d4241d6d7d5` | Deferred | Read/Write | Read | Release | Controlled - only with explicit human approval |
| LR 14 | Autonomous Ops | `82fcfcf9-7014-4d52-9ba3-e4addb3e559d` | Deferred | Read + comment | Read | Read | None |

No agent has all permissions. No agent has direct write access to `main`. No agent has production authority except LR 13 Release Manager under human approval.

## 2. Activation waves (doc 19 step 7)

- **Wave 1:** LR 02 Product Manager, LR 03 Architect, LR 04 Backend Engineer, LR 07 QA/Evaluation, LR 08 Security Engineer, with LR 01 Orchestrator as coordination hub.
- **Registered but NOT activated:** LR 05, LR 06, LR 09, LR 10, LR 11, LR 12 (documentation agent role used in this bootstrap run only by user instruction), LR 13, LR 14. Wave assignment for these is not defined in the baseline.
- **User decision required:** doc 19 says start with five bots and not all 13 at once, while the user registered 14 agents. This registry follows doc 19 (activate Wave 1 only). Also: Wave 1 contains no Code Reviewer (LR 11), so the independent-review rule (doc 16 s11) has no agent reviewer for Backend PRs (C-13), and doc 19 step 10 says coding bots operate autonomously only after the runtime exists (C-14).

## 3. Rules common to all agents

**Prohibited for every agent (doc 16 s9):** push directly to protected main; disable CI checks; modify branch protection; retrieve production secrets; approve own changes; merge own PR; deploy to production without release policy approval. No silent blocked-to-completed transitions (doc 16 s6). No agent may weaken a safety control (doc 16 s13).

**Human approval ALWAYS required (user-supplied list, superset of doc 16 s15):** production deployment; authentication/authorization changes; security-policy changes; model/tool-permission changes; destructive migrations; sensitive-data policy changes; external payment authority; irreversible external actions; safety-critical workflow changes; major-version releases. Human owner: Ojas Sharma.

**Stop-and-escalate conditions (doc 16 s13):** requirements conflict; required permission unavailable; security impact unclear; acceptance criteria cannot be satisfied; tests nondeterministic; production access requested; task scope expands materially; external system behavior ambiguous; would need to weaken a safety control. Escalation target is not defined in the baseline; this registry uses LR 01 Orchestrator then the human owner (*derived*).

**Independent review:** implementer and reviewer must be separate agent identities; the reviewer must not inherit the implementer's private reasoning (doc 16 s11). Recommended chain: Requirement -> Implementation bot -> CI -> Security -> QA -> Independent reviewer -> Human approval where required -> Release.

**Completion (doc 16 s18):** acceptance criteria satisfied; required tests pass; security checks pass or have accepted findings; documentation updated; Jira status synchronized; PR ready for independent review. Jira DONE per doc 17 s7 is not set by implementation bots.

**Registry fields required by doc 16 s4 and their current state (all agents):**

| Field | Value |
|---|---|
| immutable bot ID | Platform agent id above (immutability not verified) |
| role / mission | See section 4 |
| versioned system prompt / prompt id | TBD - not defined in baseline |
| allowed tools / denied tools | Described per agent in section 4 at policy level; concrete tool allowlists: TBD - not defined in baseline |
| repository permissions / Jira permissions | See summary table (user baseline where given; otherwise derived) |
| model/provider | TBD - not defined in baseline (doc 18 s1 names Grok/xAI tooling for the engineering workforce; per-bot assignment undefined) |
| context sources | TBD - not defined in baseline |
| maximum task duration | TBD - not defined in baseline |
| maximum tool calls | TBD - not defined in baseline |
| token/cost budget | TBD - not defined in baseline |
| retry policy | TBD - not defined in baseline |
| escalation policy | See section 3 (derived) - formal policy TBD - not defined in baseline |
| approval requirements | Section 3 list |
| output schema | Doc 16 s8 Bot Result Contract (taskId, status, summary, filesChanged, testsRun, testsPassed, testsFailed, securityFindings, architectureChanges, risks, followUp) |
| metrics | Doc 16 s14 workforce metrics; per-bot targets TBD - not defined in baseline |
| audit policy | Doc 16 s16 fields; retention/immutability mechanism TBD - not defined in baseline |

Note: the doc 16 s7 task-contract example values (maxSteps 30, timeoutSeconds 1800, maxTokens 50000, maxUsd 5) are illustrative in the baseline and are NOT adopted as limits.

## 4. Agents

### LR 01 - Orchestrator

- **Platform agent id:** `16e987ef-66bd-427a-be3c-f4489705b4fb`
- **Activation wave:** Wave 1 (coordination hub)
- **Baseline source:** Doc 16 s2 'Workforce Orchestrator' (diagram only; no named bot in s5). Mapping to LR 01 is an inference.
- **Mission:** Coordinate the workforce: route work from the human control plane through task queue, bot registry and memory to the bots; keep durable artifacts (Jira, Git, PR, CI, reports) as the source of truth (doc 16 s2, s10).
- **Responsibilities:** Assign/claim-route tasks to the right agent; enforce implementer != reviewer assignment; track blocked work and escalate; keep the registry and waves current; request human approvals; never hold hidden conversational state as truth.
- **Allowed actions:** Read Jira/Git/CI; comment on Jira issues; assign work per registry; create Jira issues only as delegated by Product (LR 02)/human; request approvals.
- **Prohibited actions:** Writing or merging code; editing branch protection; approving any change it routed; production access; changing agent permissions or registry rules without human approval. Plus all common prohibitions (section 3).
- **Permission level:** Jira: Read/Write limited to assignment, comments, links (derived - user baseline silent); Git: Read; CI: Read; Production: None
- **Independent review:** Orchestrator configuration/registry changes: human owner (Ojas Sharma) approval required.
- **Human-approval triggers:** the always-required list in section 3 applies; additionally any action outside the permissions above.
- **Escalation:** Human owner (Ojas Sharma).
- **Model/provider, token/cost budget, max tool calls, max task duration, retry limits, versioned prompt id:** TBD - not defined in baseline

### LR 02 - Product Manager

- **Platform agent id:** `57717786-f5c2-456e-9c79-4172ad8b457c`
- **Activation wave:** Wave 1
- **Baseline source:** Doc 16 s5 Product Bot + Product Manager Bot (merged into one registered agent - inference, see C-15).
- **Mission:** Convert business goals into measurable requirements (Product Bot); maintain backlog quality, dependencies, priorities and release readiness (Product Manager Bot).
- **Responsibilities:** Write/refine requirements and acceptance criteria; create and update Jira issues and backlog metadata; propose release scope; keep Definition of Ready satisfied; backlog hygiene (weekly per doc 16 s12).
- **Allowed actions:** Read requirements; create/update Jira issues; edit requirements; change backlog metadata; propose acceptance criteria; propose release scope (doc 16 s5, doc 17 s8).
- **Prohibited actions:** Merge code; deploy; modify security policy; close implementation issues (doc 17 s8). Plus all common prohibitions (section 3).
- **Permission level:** Jira: Read/Write (user baseline); Git: Read; CI: Read (derived); Production: None
- **Independent review:** Product requirements are reviewed by Architect (LR 03) for feasibility and approved by the human owner; Product does not review its own requirements.
- **Human-approval triggers:** the always-required list in section 3 applies; additionally any action outside the permissions above.
- **Escalation:** LR 01 Orchestrator, then human owner.
- **Model/provider, token/cost budget, max tool calls, max task duration, retry limits, versioned prompt id:** TBD - not defined in baseline

### LR 03 - Architect

- **Platform agent id:** `1197d5b3-9851-4b6c-ba49-7b290220938d`
- **Activation wave:** Wave 1
- **Baseline source:** Doc 16 s5 Architect Bot.
- **Mission:** Design service boundaries, ADRs, contracts, scalability and reliability decisions.
- **Responsibilities:** Architecture baseline, ADR proposals, API/data contracts, contradiction analysis (doc 19 step 8 first task); design review of implementation.
- **Allowed actions:** Read repo/docs/Jira; create/update ADR and docs via PR (branch+PR); comment/create design tasks in Jira as delegated (derived).
- **Prohibited actions:** Implement application code (first task explicitly 'Do not implement code'); modify production configuration (doc 19 step 8); merge own PRs; approve own ADRs. Plus all common prohibitions (section 3).
- **Permission level:** Jira: Read/Write limited to design tasks and comments (derived - user baseline silent); Git: Read + branch/commit/PR for docs and ADRs only (derived); CI: Read; Production: None
- **Independent review:** ADRs and architecture changes reviewed by Security (LR 08) for security impact and approved by the human owner; Code Reviewer (LR 11) when activated. Architect does not review its own ADRs.
- **Human-approval triggers:** the always-required list in section 3 applies; additionally any action outside the permissions above.
- **Escalation:** LR 01 Orchestrator, then human owner.
- **Model/provider, token/cost budget, max tool calls, max task duration, retry limits, versioned prompt id:** TBD - not defined in baseline

### LR 04 - Backend Engineer

- **Platform agent id:** `f3bf2c12-2baa-452f-8a18-1668dbe675e8`
- **Activation wave:** Wave 1
- **Baseline source:** Doc 16 s5 Backend Bot.
- **Mission:** Implement backend services, APIs, domain logic, persistence and tests.
- **Responsibilities:** Implement assigned backend tasks on isolated branches with tests; open PRs; report structured results (doc 16 s8); attach PRs and technical comments in Jira.
- **Allowed actions:** Claim assigned tasks; update progress; attach PRs; add technical comments (doc 17 s8); create branch, commit, open/update PR within allowedFiles.
- **Prohibited actions:** Push to main; merge own PR; mark DONE; approve own work; disable CI; touch branch protection; production secrets/deploy; operating autonomously before the workforce runtime exists (doc 19 step 10; see C-14). Plus all common prohibitions (section 3).
- **Permission level:** Jira: Read/Write (user baseline), scoped to doc 17 s8 implementation-bot actions; Git: Branch + commit + PR (user baseline); no main write; CI: Read results; Production: None
- **Independent review:** Independent reviewer must be a different agent identity: Code Reviewer (LR 11) once activated; in Wave 1 (LR 11 inactive) PRs need review by Architect (LR 03) for design plus QA (LR 07) and Security (LR 08) gates, and human owner merge approval. OPEN decision C-13.
- **Human-approval triggers:** the always-required list in section 3 applies; additionally any action outside the permissions above.
- **Escalation:** LR 01 Orchestrator, then human owner.
- **Model/provider, token/cost budget, max tool calls, max task duration, retry limits, versioned prompt id:** TBD - not defined in baseline

### LR 05 - Frontend Engineer

- **Platform agent id:** `c0ef1be6-6767-428b-ad65-5a7b924b1eab`
- **Activation wave:** Deferred - registered, NOT activated (wave not defined in baseline)
- **Baseline source:** Doc 16 s5 Frontend Bot.
- **Mission:** Implement accessible, secure, tested user interfaces.
- **Responsibilities:** Implement assigned UI tasks (Next.js + TypeScript per doc 18) with tests; open PRs. Doc 19 step 12 defers UI refinement to last.
- **Allowed actions:** Same as implementation bots (doc 17 s8): claim, update progress, attach PRs, comment; branch+commit+PR within allowedFiles (derived).
- **Prohibited actions:** Same prohibitions as LR 04. Plus all common prohibitions (section 3).
- **Permission level:** Jira: Read/Write scoped to implementation-bot actions (derived); Git: Branch + commit + PR (derived); CI: Read results; Production: None
- **Independent review:** Code Reviewer (LR 11); QA (LR 07) and Security (LR 08) gates. Not LR 05 itself.
- **Human-approval triggers:** the always-required list in section 3 applies; additionally any action outside the permissions above.
- **Escalation:** LR 01, then human owner.
- **Model/provider, token/cost budget, max tool calls, max task duration, retry limits, versioned prompt id:** TBD - not defined in baseline

### LR 06 - Agent Engineer

- **Platform agent id:** `a3876af5-e951-4870-a911-c639a2e984d8`
- **Activation wave:** Deferred - registered, NOT activated
- **Baseline source:** Doc 16 s5 Agent Engineer Bot.
- **Mission:** Implement agent workflows, prompts, schemas, tool adapters, policy integration and evaluation.
- **Responsibilities:** Implement customer agent runtime pieces (doc 18 s3-4, s9) and workforce-runtime pieces assigned (doc 20) with tests; changes to prompts/tool permissions require human approval.
- **Allowed actions:** Implementation-bot actions (doc 17 s8); branch+commit+PR (derived).
- **Prohibited actions:** Same as LR 04; changing model/tool permissions without human approval; weakening policy engine or tool allowlists. Plus all common prohibitions (section 3).
- **Permission level:** Jira: Read/Write scoped (derived); Git: Branch + commit + PR (derived); CI: Read results; Production: None
- **Independent review:** Code Reviewer (LR 11) + Security (LR 08) + Red Team (LR 09) for agent/tool behaviour; not LR 06 itself.
- **Human-approval triggers:** the always-required list in section 3 applies; additionally any action outside the permissions above.
- **Escalation:** LR 01, then human owner.
- **Model/provider, token/cost budget, max tool calls, max task duration, retry limits, versioned prompt id:** TBD - not defined in baseline

### LR 07 - QA / Evaluation

- **Platform agent id:** `c275d521-c638-449f-9f35-83d2d7ffd668`
- **Activation wave:** Wave 1
- **Baseline source:** Doc 16 s5 QA/Evaluation Bot.
- **Mission:** Verify functional correctness, regression safety, agent behavior and acceptance criteria.
- **Responsibilities:** Run/validate tests and acceptance criteria; evaluation of agent behaviour; flaky-test analysis; approve the QA gate (doc 17 s8).
- **Allowed actions:** Add findings; transition to validation/rework; approve its specific gate (doc 17 s8); write tests via PR (derived).
- **Prohibited actions:** Approve work it implemented; mark DONE; merge; weaken test criteria to pass; production access. Plus all common prohibitions (section 3).
- **Permission level:** Jira: Read/Write scoped to findings and gate transitions (derived from doc 17 s8; user baseline silent); Git: Read + test-code PRs (derived); CI: Read results; Production: None
- **Independent review:** Test code reviewed by a different agent (Architect or Code Reviewer); QA verdicts are not self-approvable.
- **Human-approval triggers:** the always-required list in section 3 applies; additionally any action outside the permissions above.
- **Escalation:** LR 01, then human owner.
- **Model/provider, token/cost budget, max tool calls, max task duration, retry limits, versioned prompt id:** TBD - not defined in baseline

### LR 08 - Security Engineer

- **Platform agent id:** `faa69525-3b4f-4dce-804a-88ac4c236930`
- **Activation wave:** Wave 1
- **Baseline source:** Doc 16 s5 Security Bot.
- **Mission:** Identify vulnerabilities, unsafe dependencies, secret exposure, authorization failures and insecure agent/tool behavior.
- **Responsibilities:** Security review of PRs/ADRs; dependency and secret scanning review; maintain threat model proposals; approve the security gate; raise Security blockers (doc 17 s9 -> BLOCKED).
- **Allowed actions:** Add findings; transition to validation/rework/blocked; approve its specific gate (doc 17 s8); read security systems (user baseline).
- **Prohibited actions:** Autonomous approval of security exceptions (doc 20 non-goals); security-policy changes without human approval; modify branch protection; production access. Plus all common prohibitions (section 3).
- **Permission level:** Jira: Read/Write (user baseline); Git: Read; CI: Read (security artifacts); Production: None
- **Independent review:** Security findings/policy proposals reviewed by Red Team (LR 09) when active and approved by the human owner; Security does not approve its own policy changes.
- **Human-approval triggers:** the always-required list in section 3 applies; additionally any action outside the permissions above.
- **Escalation:** Human owner (security impact unclear is a stop condition, doc 16 s13).
- **Model/provider, token/cost budget, max tool calls, max task duration, retry limits, versioned prompt id:** TBD - not defined in baseline

### LR 09 - Red Team

- **Platform agent id:** `3115eb58-1c22-4d1e-bd1f-9f188802f5c9`
- **Activation wave:** Deferred - registered, NOT activated
- **Baseline source:** Doc 16 s5 Red Team Bot.
- **Mission:** Actively attempt prompt injection, tool abuse, authorization bypass, data leakage, fabricated success and other adversarial behaviors.
- **Responsibilities:** Adversarial testing in non-production only (doc 19 step 14 prompt-injection/authorization tests).
- **Allowed actions:** Read; run adversarial tests against local/dev/staging targets explicitly authorised by the human owner; file findings in Jira.
- **Prohibited actions:** Any testing against production; exploiting findings; storing exfiltrated data; modifying code or policy. Plus all common prohibitions (section 3).
- **Permission level:** Jira: Read/Write findings only (derived); Git: Read; CI: Read; Production: None (testing against production prohibited)
- **Independent review:** Findings triaged by Security (LR 08); Red Team does not triage its own findings.
- **Human-approval triggers:** the always-required list in section 3 applies; additionally any action outside the permissions above.
- **Escalation:** Human owner.
- **Model/provider, token/cost budget, max tool calls, max task duration, retry limits, versioned prompt id:** TBD - not defined in baseline

### LR 10 - SRE / DevOps

- **Platform agent id:** `5fa97934-58a9-40a2-b044-a7bca0d521ec`
- **Activation wave:** Deferred - registered, NOT activated
- **Baseline source:** Doc 16 s5 SRE/DevOps Bot.
- **Mission:** Infrastructure, deployment, observability, reliability, backups, recovery and operational automation.
- **Responsibilities:** Terraform/Docker/CI/observability changes via PR; DR planning inputs (RPO/RTO undefined).
- **Allowed actions:** Implementation-bot actions; branch+commit+PR on infrastructure/ and CI files (derived).
- **Prohibited actions:** Apply infrastructure changes to production; retrieve production secrets; destructive migrations; change CI to bypass checks. Plus all common prohibitions (section 3).
- **Permission level:** Jira: Read/Write scoped (derived); Git: Branch + commit + PR on infra/CI paths (derived); CI: Read + pipeline definition via PR; Production: None (changes need human approval and Change issue)
- **Independent review:** Security (LR 08) + Architect (LR 03) + human approval for infra changes; not LR 10 itself.
- **Human-approval triggers:** the always-required list in section 3 applies; additionally any action outside the permissions above.
- **Escalation:** LR 01, then human owner.
- **Model/provider, token/cost budget, max tool calls, max task duration, retry limits, versioned prompt id:** TBD - not defined in baseline

### LR 11 - Code Reviewer

- **Platform agent id:** `9e35ca41-62aa-4edb-861d-54bc45626a51`
- **Activation wave:** Deferred - registered, NOT activated (see C-13: needed for independent review)
- **Baseline source:** Doc 16 s5 Code Reviewer Bot.
- **Mission:** Independently review implementation against requirements, architecture and engineering standards.
- **Responsibilities:** PR review; must not inherit the implementer's private reasoning (doc 16 s11).
- **Allowed actions:** Read repo/PRs; submit review comments/approvals on PRs authored by other agents.
- **Prohibited actions:** Reviewing its own code; merging; pushing; implementing the change it reviews. Plus all common prohibitions (section 3).
- **Permission level:** Jira: Read + comment (derived); Git: Read + PR review; CI: Read; Production: None
- **Independent review:** Reviews others; its own changes (if any) reviewed by Architect.
- **Human-approval triggers:** the always-required list in section 3 applies; additionally any action outside the permissions above.
- **Escalation:** LR 01, then human owner.
- **Model/provider, token/cost budget, max tool calls, max task duration, retry limits, versioned prompt id:** TBD - not defined in baseline

### LR 12 - Documentation

- **Platform agent id:** `d91dff24-1350-4652-98cb-e94b0de7bbb3`
- **Activation wave:** Deferred - registered, NOT activated (note: used as documentation agent in this bootstrap run per user instruction)
- **Baseline source:** Doc 16 s5 Documentation Bot.
- **Mission:** Keep ADRs, API documentation, runbooks, diagrams and release notes synchronized with implementation.
- **Responsibilities:** Confluence/Git docs sync; documentation drift (daily per doc 16 s12). Named documentation agent in Confluence page metadata.
- **Allowed actions:** Create/update Confluence pages in the LifeRescue space; docs PRs (branch+commit+PR); Jira comments.
- **Prohibited actions:** Change security/policy content without Security + human approval; merge own PR; edit code. Plus all common prohibitions (section 3).
- **Permission level:** Jira: Read + comment (derived); Git: Branch + commit + PR on docs/ (derived); CI: Read; Production: None
- **Independent review:** Docs reviewed by Architect (LR 03) or Product (LR 02) depending on subject; not self-reviewed.
- **Human-approval triggers:** the always-required list in section 3 applies; additionally any action outside the permissions above.
- **Escalation:** LR 01, then human owner.
- **Model/provider, token/cost budget, max tool calls, max task duration, retry limits, versioned prompt id:** TBD - not defined in baseline

### LR 13 - Release Manager

- **Platform agent id:** `47cf9085-ea3b-4fe7-8f4c-0d4241d6d7d5`
- **Activation wave:** Deferred - registered, NOT activated
- **Baseline source:** Doc 16 s5 Release Manager Bot.
- **Mission:** Verify release gates, produce release candidates, coordinate approvals and execute governed releases.
- **Responsibilities:** Move release-ready issues; record release results (doc 17 s8); release candidate assembly.
- **Allowed actions:** Move release-ready issues; record release results; trigger CI release pipelines (user baseline 'CI release'); production deployment only with human approval.
- **Prohibited actions:** Deploy to production without human approval and release policy approval; skip gates; major-version release without human approval; mark work it did not verify as released. Plus all common prohibitions (section 3).
- **Permission level:** Jira: Read/Write (user baseline); Git: Read; CI: Release (user baseline); Production: Controlled - only with explicit human approval
- **Independent review:** Every production release requires human approval (Ojas Sharma); release gates verified independently of the implementer.
- **Human-approval triggers:** the always-required list in section 3 applies; additionally any action outside the permissions above.
- **Escalation:** Human owner.
- **Model/provider, token/cost budget, max tool calls, max task duration, retry limits, versioned prompt id:** TBD - not defined in baseline

### LR 14 - Autonomous Ops

- **Platform agent id:** `82fcfcf9-7014-4d52-9ba3-e4addb3e559d`
- **Activation wave:** Deferred - registered, NOT activated
- **Baseline source:** Doc 20 Phase F 'Autonomous Operations' and doc 16 s12 Continuous Workforce (no named bot in doc 16 s5; mapping is an inference).
- **Mission:** Observe continuously (dependency monitoring, flaky tests, documentation drift, security monitoring, cost anomalies, deployment health, incident triage); continuous autonomous production mutation is prohibited.
- **Responsibilities:** Scheduled/event-driven observation and reporting (doc 16 s12); file Jira issues/comments for findings as delegated.
- **Allowed actions:** Read-only observation of repo, CI, telemetry; report findings; comment in Jira (derived).
- **Prohibited actions:** Any autonomous production mutation; secret retrieval; destructive operations; changing policy. Plus all common prohibitions (section 3).
- **Permission level:** Jira: Read + comment (derived); Git: Read; CI: Read; Production: None (read-only observability only once defined)
- **Independent review:** Reports are inputs; actions on them go through the normal implement/review chain.
- **Human-approval triggers:** the always-required list in section 3 applies; additionally any action outside the permissions above.
- **Escalation:** LR 01, then human owner.
- **Model/provider, token/cost budget, max tool calls, max task duration, retry limits, versioned prompt id:** TBD - not defined in baseline

## 5. Review matrix (implementer -> reviewer)

| Author | Wave 1 reviewer(s) | Full-workforce reviewer(s) |
|---|---|---|
| LR 02 Product Manager | LR 03 Architect (feasibility) + human approval | same |
| LR 03 Architect | LR 08 Security (impact) + human approval | + LR 11 Code Reviewer |
| LR 04 Backend Engineer | LR 03 Architect (design), LR 07 QA gate, LR 08 Security gate, human merge approval (no LR 11 in Wave 1 - OPEN C-13) | LR 11 Code Reviewer + gates |
| LR 05 / LR 06 | n/a (not active) | LR 11 + gates (+ LR 09 for LR 06) |
| LR 07 QA | LR 03 Architect (test design) | LR 11 |
| LR 08 Security | human owner | LR 09 Red Team + human |
| LR 10 SRE | n/a (not active) | LR 08 + LR 03 + human |
| LR 12 Documentation | n/a (not active) | LR 03 / LR 02 |
| LR 13 Release Manager | n/a (not active) | human approval for production |

The rule `implementer != reviewer` is enforced in this matrix; enforcement in tooling does not exist yet (no runtime, no branch protection).

## 6. Open items affecting this registry

- C-03 (5 vs 13 vs 14 agents), C-13 (no Wave 1 independent code reviewer), C-14 (autonomous coding before runtime), C-15 (LR 02 = Product Bot + Product Manager Bot), C-22 (per-bot limits TBD), C-24 (user's 'Jira RW' baseline vs doc 17 s8 narrower permissions): see Open Decisions and Conflicts.
