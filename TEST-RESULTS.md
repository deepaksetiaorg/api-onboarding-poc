# Test results

**Date:** 2026-10-27  
**Repo:** `setia141/api-onboarding-poc` (private, personal account) for all tests below, then transferred to `deepaksetiaorg/api-onboarding-poc` (see [Org move](#org-move)). Issue numbers are unchanged.  
**Code tested:** `main` at `089e538` (access control `0e24ddf`, undo of rejected actions `5e8df35`, guard `39219a0`, parent close fix `cd0b069`, owner assignment `c293cb9`/`3e4334c`, steps marker `089e538`)  
**How to re-run:** see [README section 7](README.md#7-how-to-test).

## Summary

| Area | Result |
|---|---|
| Unit tests: access control, guard, owner assignment, steps marker (`scripts/test_authorize.py`) | ✅ 32/32 passed |
| Unit tests: ADO webhook handler (`azure-function/test_handler.py`) | ✅ 4/4 passed |
| Local dry run: design, codegen (config + OpenAPI Generator in Docker), proxy, validation messages | ✅ Passed |
| GitHub end to end: intake → 3 forms → parent auto-closed | ✅ Passed |
| GitHub access control: submissions, edits, reopens | ✅ Passed |
| GitHub guard: close/reopen/edit of parent, step and submission issues | ✅ Passed |
| Failed workflow runs during the access-control and guard tests | 0 |
| Not tested | Apigee deploy, ADO comments/state, Azure Function deployed in Azure, scenarios that need a second GitHub account (below) |

## Test method

There was one GitHub account (`setia141`), which is also the repo admin. Roles were simulated with the `GOVERNANCE` repo variable:
- **Governance:** `GOVERNANCE=@setia141`.
- **API owner only:** `GOVERNANCE=@someone-else`, tester listed on the API's Owners line.
- **Another team:** `GOVERNANCE=@someone-else`, tester not on the API's Owners line.

`GOVERNANCE` was restored to `@setia141` after each round.

Test APIs:

| API | Parent | Steps (design / codegen / proxy) | Owners |
|---|---|---|---|
| `member-api` | #5 | #6 / #7 / #8 | `@setia141` |
| `claims-api` | #9 | #10 / #11 / #12 | `@octocat` |
| `orders-api` | #18 | #19 / #20 / #21 | `@octocat` |
| `billing-api` | #26 | #27 / #28 / #29 | `@setia141` |

> `@octocat` is a real GitHub account and was notified by the Owners line. Use non-existent or your own test accounts next time.

## Local dry run (no GitHub)

| Check | Result |
|---|---|
| Design: Spectral lint of `specs/member-api.yaml` | ✅ Passed, 5 non-blocking suggestions |
| Codegen: `codegen.yaml` + class-name preview | ✅ `MembersController`, `AddressesController`, `MemberDto`, `AddressDto`, `MemberEnvelope` (API suffix `Controller`) |
| Codegen: OpenAPI Generator `v7.10.0` in Docker (Spring) | ✅ Java project generated |
| Proxy: Apigee bundle | ✅ `member-api-proxy.zip`, 4 operations mapped |
| Validation: package `com.example.member-api` | ✅ "…no dashes… Try `com.example.memberapi`" |

## GitHub end to end

| Check | Evidence | Result |
|---|---|---|
| Intake creates parent + 3 linked sub-issues with Owners line | #5–#8, #9–#12, #18–#21, #26–#29 | ✅ |
| Design form → lint report, submission and step closed | #13 | ✅ |
| Codegen form → class preview + downloadable code | #25 (also in the earlier repo instance) | ✅ |
| Proxy form → bundle download | #15 | ✅ |
| All steps closed → parent closes with "🎉 All steps are done" | #26 | ✅ |
| Invalid answer → fix list + `needs-changes` label, submission stays open | #22 | ✅ |

The full happy path (intake → design → codegen → proxy → parent auto-closed, with OpenAPI Generator) also passed before the repo was recreated to remove old history. Those issues were deleted with the old repo.

## Access control: form submissions

| # | Scenario | Evidence | Expected | Result |
|---|---|---|---|---|
| 1 | Governance submits for an API it doesn't own | #13 | Runs | ✅ |
| 2 | Owner (not governance) submits for own API | #15 | Runs | ✅ |
| 3 | Another team submits | #14, #30 | 🔒 "isn't an owner", own issue closed as not planned | ✅ |
| 4 | Pre-filled API name changed to another team's issue | #16 | 🔒 "API name doesn't match" | ✅ |
| 5 | Form pointed at the wrong step | #17 | 🔒 "isn't a design step issue" | ✅ |
| 6 | Form pointed at a hand-made issue with fake owners | unit test | 🔒 Rejected | ✅ (unit) |
| 7 | Non-owner edits an owner's (closed) submission | #13 | ↩️ Body restored, still closed/completed, nothing ran | ✅ |
| 7b | Non-owner reopens an owner's completed submission | #13 | ↩️ Closed again as completed | ✅ |
| 8 | Non-governance starts an onboarding | intake run | ❌ "Only the governance team can start an onboarding" | ✅ |
| – | Owner edits own closed submission | #15 | Allowed, edit kept, no re-run | ✅ |

## Guard: close / reopen / edit of onboarding issues

Before the guard (`progress.yml`), a non-owner closing the three step issues of `orders-api` made the bot post "🎉 All steps are done" and close #18 with nothing run. The owner list (#18) and a step's parent link (#20) could also be edited to gain access (#24, #25). The guard fixes all of these:

| # | Scenario | Evidence | Expected | Result |
|---|---|---|---|---|
| 11 | Non-owner closes someone else's open submission | unit test | ↩️ Reopened | ✅ (unit) |
| 12 | Non-owner closes all 3 step issues | #19, #20, #21, #18 | ↩️ Each reopened, parent stays open | ✅ |
| 13 | Owner closes own 3 step issues | #27, #28, #29, #26 | Stay closed, parent closes | ✅ |
| 13b | Owner reopens own step issue | #27 | Allowed | ✅ |
| 14a | Non-governance closes a parent | #26 | ↩️ Reopened | ✅ |
| 14b | Owner (not governance) reopens a completed parent | #26 | ↩️ Closed again as completed | ✅ |
| 15 | Non-governance adds self to Owners line | #18, then #30 | ↩️ Reverted, next form still rejected | ✅ |
| 16 | Non-governance changes a step's hidden parent link | #20 | ↩️ Reverted | ✅ |
| 17 | Governance closes, reopens and edits a parent | #18 | All allowed | ✅ |

## Owner assignment (`c293cb9`, `3e4334c`)

Test API `assign-api`: parent #36, steps #37 / #38 / #39. Owners at intake: `@setia141` and the made-up `@nobody-owner-zx81q` (confirmed not to exist on GitHub).

| # | Scenario | Evidence | Expected | Result |
|---|---|---|---|---|
| 18 | Intake assigns individual owners to step issues | #36–#39 | `setia141` assigned to #37–#39, parent unassigned, ⚠️ comment for the made-up name, Owners line in code format (no pings) | ✅ |
| 19 | Governance removes an owner (step #39 already closed) | #36 | Unassigned on #37 and #38, #39 keeps its assignee, summary comment | ✅ |
| 20 | Governance adds the owner back | #36 | Assigned on #37 and #38 only | ✅ |
| 21 | Assigned by hand but not an owner, submits a form | #37, #40 | 🔒 Rejected: assignees never grant access | ✅ |
| – | Rejection comments list owners without pinging them | unit test | Owners shown as `` `@name` `` | ✅ (fixed in `3e4334c` after #40 showed a plain mention) |

Unit tests: 30/30 passed.

## Sub-issue tampering (`089e538`)

GitHub doesn't document who can attach or detach sub-issues; assume Triage and above. "All steps done" now reads the parent's `steps` marker (governance-protected) instead of the sub-issue list.

| # | Scenario | Evidence | Expected | Result |
|---|---|---|---|---|
| 22 | Unfinished step #42 detached from parent #41 via the API, then every **attached** step (#43, #44) closed | #41–#44, Guard log "Parent #41: 2/3 steps done" | Parent stays open | ✅ |
| – | The detached step is then closed | #42, #41 | Parent closes with "🎉 All steps are done" | ✅ |
| – | Parents without a `steps` marker (created earlier) | unit test | Fall back to the sub-issue list | ✅ (unit) |

## Org move

Repo transferred to `deepaksetiaorg/api-onboarding-poc` (commit `57cb921`).

| Check | Evidence | Result |
|---|---|---|
| Issues, history and `GOVERNANCE` variable carried over | 44 issues | ✅ |
| Visibility after transfer | — | ⚠️ The transfer left it **public** for about 2–3 minutes. Set back to private straight away, then confirmed anonymous access returns 404. 0 forks, 0 stars |
| Workflows with the org's read-only default token | intake + design runs | ✅ Workflows declare their own `permissions`, so no org change was needed |
| Teams | `api-governance` (Write), `member-squad` (Read) | ✅ Created; tester is only in `api-governance` |
| Intake with a team + a person as owners | #45–#48 | ✅ Team mentioned (`@deepaksetiaorg/member-squad`), person assigned to the 3 steps |
| Design form in the org | #49 | ✅ Ran, step #46 closed |
| Branch protection / enforced CODEOWNERS | — | ❌ Not available on GitHub Free for private repos. `.github/CODEOWNERS` added (review requests only) |
| Team-based owner/governance checks | see below | ✅ With `TEAM_READ_TOKEN` (classic token, `read:org` only, set by the repo admin) |

**Team checks** (`TEAM_READ_TOKEN` set 2026-10-27; tester `setia141` is in `api-governance`, not in `member-squad`):

| # | Scenario | Evidence | Expected | Result |
|---|---|---|---|---|
| T1 | `GOVERNANCE=api-governance` (team only), member starts onboardings | #50, #53 | Intake runs | ✅ |
| T2 | Not in governance, member of the owner team `api-governance` submits | #58 | Runs | ✅ |
| T3 | Not in governance, not in owner team `member-squad`, submits | #59 | 🔒 "isn't an owner of `teamother-api` (owners: `member-squad`)" | ✅ |
| – | Two onboardings started at the same time | #50–#57 | Interleaved issue numbers kept apart by the `steps` marker | ✅ |

`GOVERNANCE` left as `@setia141, api-governance`, so a person still works if the token expires.

## Not tested / known issues

| Item | Status |
|---|---|
| Real second account with Read / Triage / Write roles (scenarios 6, 7, 11 by a different person) | Needs a second GitHub account. Covered by unit tests |
| Scenarios 9 (owners changed) and 10 (no owners) | Not run live |
| Apigee deploy, ADO comments and state change, Azure Function in Azure | Not run (no Apigee/ADO/Azure setup) |
| Closing several steps at the same moment can post "🎉 All steps are done" twice | Known, harmless. Parent is closed once |
| Anyone with Write access can change the workflows themselves | By design of GitHub. Use an org, keep Write for governance, protect `.github/` and `scripts/` |
| #23 was a real form submission rejected while `GOVERNANCE` was temporarily changed for testing | Resubmit if still needed |
