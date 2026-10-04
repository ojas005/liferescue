# PR <-> Jira link check: CLI contract (KAN-20)

**Task:** KAN-20 (Jira/Git integration foundation). **Script:** [`scripts/check_pr_link.py`](../scripts/check_pr_link.py). **Tests:** [`scripts/test_check_pr_link.py`](../scripts/test_check_pr_link.py).
**Status:** the script is not wired into CI. LR 10 owns `.github/workflows/*` and will add the job; this page is the contract for that job. The rules marked **PROPOSED ASSUMPTION - REQUIRES HUMAN APPROVAL** have not been approved by Ojas Sharma.

The check answers one question: *is this pull request linked to the Jira issue that its branch names?* It is a pure string check. It never calls Jira or GitHub, never starts another program, and never evaluates its input.

## Inputs (all hostile data)

The PR title, PR body and head branch are written by whoever opens the PR. The script only compares them with fixed patterns.

| Variable | Meaning | Limits |
|---|---|---|
| `PR_TITLE` | PR title (single line) | at most 500 characters, no line break, no control characters |
| `PR_BODY` | PR body (may be empty, may have line breaks) | at most 65536 characters; NUL, other control characters (except tab, CR, LF), DEL and bidirectional override characters are refused |
| `PR_BRANCH` | PR head branch name | at most 100 characters; must pass `scripts/check-branch-name.py` |
| `PR_JSON_FILE` | alternative to the three variables: path of a JSON file | object with exactly the keys `title`, `body`, `branch`; `body` may be `null` (read as empty); at most 1 MiB |

- Use either the three variables **or** `PR_JSON_FILE`, never both (exit 2).
- All three variables must be **set** (an empty value is allowed to be set and is then invalid, exit 1; an unset variable is a configuration error, exit 2).
- The script takes **no command-line arguments and has no options**. Any argument, including `-h`, `--help` and `--`, is a usage error (exit 2) and is not echoed. Values are never used as options, paths or shell text.
- In a workflow pass the values through `env:` and never interpolate `${{ github.event.pull_request.title }}` (or body, or `head_ref`) into a `run:` line (script injection):

```yaml
# example for LR 10 (not part of this change)
- name: Check PR links Jira issue
  env:
    PR_TITLE: ${{ github.event.pull_request.title }}
    PR_BODY: ${{ github.event.pull_request.body }}
    PR_BRANCH: ${{ github.event.pull_request.head.ref }}
  run: python3 scripts/check_pr_link.py
```

## Exit codes

| Code | Meaning | Output |
|---|---|---|
| 0 | the PR is linked | stdout: `OK: PR is linked to Jira issue KAN-<n>` |
| 1 | invalid (a rule failed, or an input is malformed) | stderr: one line per problem, `INVALID <CODE>: <fixed text>`; if the branch is involved, a last line `branch (escaped): <ascii repr, at most 80 characters>` |
| 2 | usage or configuration error (an argument was given, a variable is unset, the JSON file is unreadable or has the wrong shape, both input styles given) | stderr: `error: <fixed text>` |

A CI step must treat **any non-zero exit code as failure**. The only text taken from the input and printed is the escaped, length-bounded branch name; everything else is a fixed message, so a PR cannot forge a log line, a workflow command (`::error::`) or an `OK:` line.

### Reason codes (stable vocabulary)

`INPUT_MALFORMED`, `BRANCH_INVALID`, `BRANCH_VALIDATOR_UNAVAILABLE`, `PROTECTED_ISSUE`, `PROTECTED_ISSUE_LINK`, `KEY_NOT_IN_TITLE_OR_BODY`, `BODY_LACKS_JIRA_REFERENCE`, `LOOKALIKE_HOST`, `NON_HTTPS_JIRA_URL`, `USERINFO_IN_URL`, `JIRA_URL_BAD_FORM`. The fixed texts are in `CODES` in the script.

## Rules

1. **Branch.** It must pass the branch-name validator (same file, loaded from `scripts/check-branch-name.py`: `<type>/KAN-<number>-<description>`, `re.fullmatch`, no normalization). If the validator cannot be loaded the result is invalid (fail closed). Its key `KAN-<n>` is the *branch key*.
2. **Key match.** The branch key must appear as a whole `KAN-<n>` token in the title or the body. Matching is **case-sensitive**: `kan-20` does not count. `KAN-200`, `KAN-2`, `KAN-020`, `XKAN-20`, `KAN-20x`, `KAN-20-1` and look-alike Unicode (full-width letters or digits, Kelvin sign, Cyrillic letters, non-breaking hyphen) are different tokens.
3. **Body reference.** The body itself must contain the branch key, either bare (`KAN-20`) or in a Jira URL. A title-only reference is not enough. (Decision: stricter than "any Jira key in the body", so the body cannot point at another issue.)
4. **Jira URLs.** A Jira URL is `https://liferescue.atlassian.net/...` with the **exact** host (scheme and host are case-insensitive), no user information, port absent or `443`, and the key in its path or query. Refused wherever they appear in the title or the body:
   - any other host containing `liferescue` or `atlassian.net` (`liferescue.atlassian.net.evil.com`, `evil.liferescue.atlassian.net`, `liferescue-atlassian.net`, `other.atlassian.net`, `atlassian.net`);
   - the Jira host name inside another URL's path, query or fragment (`https://evil.com/liferescue.atlassian.net/...`) or a scheme-less look-alike such as `liferescue.atlassian.net.evil.com/browse/KAN-20`;
   - user information (`https://user:pass@liferescue.atlassian.net/...`, `https://liferescue.atlassian.net@evil.com/...`, backslash tricks);
   - a Jira URL over `http` or any scheme other than `https`; a port other than 443;
   - internationalised hosts (any non-ASCII host or an `xn--` label) in any URL of the PR text (**PROPOSED ASSUMPTION - REQUIRES HUMAN APPROVAL**: refused outright because Unicode look-alikes cannot be told apart reliably; a legitimate IDN link must be removed from the PR text);
   - a bracketed host that mentions the Jira host.
   Other https links (GitHub, `community.atlassian.com`, ...) are not touched.
5. **Protected issues. PROPOSED ASSUMPTION - REQUIRES HUMAN APPROVAL.** The KAN-20 plan (N1) says the live backlog issues KAN-1..KAN-3 and the example project SAM1 "must not be touched". This check therefore (a) denies a branch whose key is KAN-1, KAN-2 or KAN-3 (`PROTECTED_ISSUE`), and (b) denies a Jira URL on the exact host that points at KAN-1..KAN-3 or at a `SAM1-<n>` issue (`PROTECTED_ISSUE_LINK`). A plain-text mention of such a key is not a link and is allowed. A SAM1 branch is already refused by the branch validator.

Everything fails closed: a missing or non-text input, an over-long input, a control character, an internal error or an unavailable validator gives exit 1 (or 2 for configuration errors), never 0.

## Limits

- It checks the *text*. It does not know whether the issue exists, whether it is the right issue, or whether the PR author may work on it. A reviewer still reads the PR.
- Case-sensitivity, the stricter body rule and the IDN refusal are decisions, not facts from Jira; see the assumptions above.
- The scheme-less look-alike scan is deliberately strict and fails closed: any dotted token that contains `liferescue.` (other than the exact Jira host) is refused, so a PR text that mentions, for example, a clone URL ending in `liferescue.git` or a file named `liferescue.md` is reported as `LOOKALIKE_HOST`. Write such names without the dotted suffix (for example `github.com/ojas005/liferescue/pull/9`). Whether to narrow this is for Ojas and LR 10 to decide with the CI job.
- Branch names created before the KAN rule (for example `chore/bootstrap-repository-baseline`) fail rule 1. How they are grandfathered is for the workflow to decide (ADR-0017 point 7); this script does not exempt anything.

See also: [Jira comment and label conventions](jira-comment-label-conventions.md), [Jira status mapping and transition allowlist](jira-transition-allowlist.md).
