# Project Prometheus v2: build plan and Claude Code prompts

This plan merges the EdgeLab design with what the 28 September 2026 audit found in your code (commit 70a8e96). It builds on Prometheus instead of replacing it. Your engine, laws, LORD++ gate, canaries, point-in-time data layer and dashboard stay. What changes is everything the audit showed is missing or broken, plus the EdgeLab pieces you don't have yet.

There are 15 prompts in three stages. Stage A (P0 to P9) makes the system trustworthy. Stage B (P10 and P11) makes the search smarter. Stage C (P12 to P14) runs it forward and has it checked independently.

Save this file in your repo as docs/BUILD_PLAN.md. Every prompt tells Claude Code to read it, so the reasoning travels with the code. Nothing here is financial advice, and nothing here can guarantee profit.

## Before you start

These take about 20 minutes, by hand.

- Rotate the Anthropic API key you pasted into the chat. Create a new key in the Anthropic Console, put it in Railway's variables, then delete the old one. From now on, keys live only in Railway variables and your local .env.
- Move the repo out of OneDrive, for example to C:\dev\Project_Prometheus. OneDrive syncing a live git repository can lock or corrupt files.
- Add this file to the repo as docs/BUILD_PLAN.md (the audit stays at AUDIT_REPORT.md in the root) and commit both.
- Stop red builds from deploying. In GitHub, protect main so CI must pass. In each Railway service's settings, turn on "Wait for CI": deployments then wait while GitHub Actions run, and are skipped if any fail. Check it's still on after any manual redeploy, because some users report it resetting.
- Set up alerts you'll actually see (P1 needs them): a free dead-man's-switch service such as healthchecks.io, plus one alert channel (a Telegram bot, a Discord webhook or email). Put the URLs and tokens in Railway variables, never in a chat.

## What "100% works" can honestly mean

No one can build a system that is guaranteed to find a profitable edge. The evidence you already have (0 discoveries in 102 gate tests, and the August 2026 study from the first plan, where no AI-discovered strategy survived honest testing) says most ideas will fail. What you can build, and what these prompts build, is a system that is verified to be honest and safe, so you can trust whatever it tells you, including "nothing beats holding the index".

When all prompts are done, each of these seven guarantees is backed by an automated test that runs every night. If any turns red, promotions stop and you get a message.

1. No peeking at the future. A strategy that uses tomorrow's information is caught three ways: by its structure, by re-running it on data cut off at random dates, and by a "too good to be true" check on its results.
2. Every try is counted. Every backtest goes into one tamper-evident ledger, and the bar for "real" rises automatically as the count grows.
3. Fakes don't pass. Planted random strategies pass the gate no more often than the designed error rate.
4. Real edges get found, and you know how big they must be. Planted edges of known size go through the same gate, which tells you the smallest edge the system can detect.
5. Nothing is trusted until it passes unseen data. Promotion needs one-shot tests on coins the system never touched and on months that hadn't happened yet.
6. Risk limits bite. Daily-loss, drawdown and exposure limits actually stop paper trading.
7. Silence is an alarm. If data goes stale, a job hangs or a check stops running, you hear about it within a day.

## The decisions the audit forced

These are the parts of the plan that aren't obvious. The prompts refer to them by number.

**D1. The vault can't be fixed by making it longer.** The research loop has already looked at every day before 16 September 2026, roughly 450,000 times. Moving the holdout boundary back would relabel data the search has already seen as "unseen". Only three kinds of data are still clean: days from 16 September 2026 onward, coins the system has never touched, and the future. So the vault becomes two vaults.

The time vault runs in six-month epochs. Epoch 1 covers 16 September 2026 to 15 March 2027 and is evaluated once, on 16 March 2027. That half-year is then released into the research data and epoch 2 begins. The research data is frozen on purpose, with a known release date. (It isn't broken: since 16 September every new bar has been routed into the holdout by design.)

The symbol vault comes out of fixing survivorship bias. Rebuilding the coin universe properly adds many coins your loop has never seen, probably more than a hundred. Half of them are sealed permanently, and each finished strategy gets one shot at them, so an honest verdict takes weeks instead of months. New coins first land in a staging area the research loop can't read, so the fresh pool stays fresh until the split is made. A strategy must pass both vaults, one shot each.

**D2. Protect the gate's budget, and feed it honest numbers.** LORD++ is the most valuable honesty mechanism you have, but every test, pass or fail, lowers the threshold for the next test until something is discovered. After 102 tests of candidates that were never going to pass, the next threshold is already 9.4 × 10⁻⁶. From now on, only strategies that survive every cheaper robustness check reach the gate, and the p-value the gate uses comes from the symbol vault, not from the data the strategy was picked on (a p-value computed on the data a strategy was picked from is biased toward looking significant). Never reset the gate.

**D3. Beat a fair opponent, not a falling coin.** Seven of your top ten are ATOM strategies. ATOM fell a lot in the research window, so any rule that sat in cash part of the time "beat" holding it. That isn't skill. The fair opponent for a long/flat strategy is its random twin: same coin, same share of time invested, same number of trades and costs, but with its in-market and flat spells shuffled. A strategy shows timing skill only if it beats at least 95% of 1,000 twins.

**D4. Catch cheating by its results, not only by its structure.** In the audit, a signal that knew each day's return scored +22,837 points with p = 0, and the accounting didn't notice. It is blocked today only because strategies must come from fixed families. Three result-based checks close the gap: re-run on truncated data and confirm past decisions don't change; add one bar of delay and confirm the result doesn't collapse; quarantine anything too good to be true. The nightly truth tests prove an oracle is caught even when the family system is bypassed.

**D5. Law 7 first, then fix the score.** Your own Law 7 says thresholds may change only after re-checking all past results, and it is still a stub. It gets built first, and the always-true score is then fixed through it, so the fix follows your own rules.

**D6. Blind the AI.** Claude has read market history. If a prompt says "ATOM, 2022", it can steer toward what it remembers worked, which is hindsight, not an edge. From now on, strategy prompts say "Asset A" and "period 3", and the AI never sees vault or paper-trading results.

**D7. Paper results are vault data.** Paper trading happens on days inside the time vault. If paper profits and losses feed breeding, rankings or the AI's critique packets, the vault leaks into the research. Paper results stay sealed from the research loop until the epoch closes.

**D8. Save raw options chains now.** Your recorder keeps per-expiry totals, but the signals worth testing (the volatility smirk, call-put IV spreads) need per-strike data, and you can't go back and collect days you didn't save. Also, the audit's "no free historical options source" is out of date: DoltHub's post-no-preference/options database is free to query without an account (as of August 2026), so options ideas can be tested on past years instead of waiting two years. Your own snapshots, which started on 28 September 2026, sit inside epoch 1, so research can't use them until March 2027. The morning report can still show them to you.

**D9. Railway skips runs; it doesn't kill them.** When a cron run is still going at the next tick, Railway skips the new run and never stops the old one. One hung AI call can therefore silently block every later run. Long research moves to an always-on worker with hard timeouts, locks and heartbeats, and cron keeps only short jobs. It also means the cut-offs the audit saw have some other cause, which P1 must find.

**D10. More searching raises the bar.** With about 450,000 backtests, a strategy has to beat the luckiest of an enormous number of random tries. The effective number is smaller, because many trials are near-copies, and P3 estimates it. Either way, the system can now confirm only large edges, while realistic edges are small. The truth tests measure the smallest edge the system can detect, and the search stops by itself when more searching hurts more than it helps.

**D11. Freeze the search while rebuilding.** Until the new gauntlet and truth tests are running, every test the old pipeline performs spends gate budget and money on rules that are about to be replaced. P0 pauses evolution, the AI steps and gate submissions. Data collection, options recording, paper plumbing and health checks keep running.

## Keep, fix, add, skip

| Area | Decision |
|---|---|
| Stack | Keep yours: FastAPI, Postgres, the polars engine, Next.js, Railway. Don't switch to EdgeLab's DuckDB, vectorbt, alphalens, Streamlit, OpenBB or Alpaca; a rewrite adds risk, not honesty. |
| Strategy language | Keep the fixed families, which make look-ahead impossible to write. Add new families where needed instead of EdgeLab's feature algebra. |
| Honesty machinery | Keep LORD++, canaries, pre-registration, DB-role isolation, append-only history and the law tests. Extend them. |
| Scoring | Replace the composite score with traffic-light statuses ranked by DSR (D5). |
| Holdout | Rebuild as time-vault epochs plus a symbol vault, wired into promotion (D1). |
| Universe | Replace the survivor list with a point-in-time universe that includes dead coins. |
| The 13 champions | Relabel as LEGACY_UNVERIFIED. No grandfathering. |
| Risk | Enforce daily loss, drawdown and total exposure. |
| Operations | Split short cron jobs from long research; timeouts, locks, heartbeats, alerts (D9). |
| Options and money flow | Build EdgeLab's "follow the big money" module on raw chains plus the DoltHub backfill (D8). |
| Research brain | Keep as is (abstracts only). Add full text later, only if paper-sourced ideas produce survivors. |
| RD-Agent comparison | Skip for now. |
| Live trading | Not built by these prompts. A human checklist comes first, then a separate project. |

## How to run the prompts

Use one fresh Claude Code session per prompt (type /clear between prompts). Where a prompt says "plan mode", press Shift+Tab until plan mode is on, so Claude Code shows you its plan before changing anything. Read the plan, approve it, then let it build.

Claude Code works on a branch and opens a pull request. CI must pass, you merge, and Railway deploys. Don't start the next prompt until the current one's "Done when" list is fully met and the verifier agent (built in P0) has tried and failed to break it.

Some prompts end with a decision only you can make, such as approving a threshold file. When that happens, stop and decide; don't let Claude Code guess. Several prompts will take more than one session, which is normal.

## Build order and progress

Claude Code ticks a box only when every "Done when" item passes, and adds a short evidence note to the Progress log at the end of this file.

Stage A: make it trustworthy

- [ ] P0 Guardrails, verifier and gap map
- [ ] P1 Keep it alive and watched
- [ ] P2 Risk limits that bite; honest paper accounting
- [ ] P3 One honest ledger
- [ ] P4 Law 7 first, then fix the score
- [ ] P5 Catch cheating by its results
- [ ] P6 Honest data: dead coins included
- [ ] P7 The vault, rebuilt
- [ ] P8 Gauntlet v2 and an honest re-run
- [ ] P9 Truth tests: the system proves itself every night

Stage B: search smarter (only after Stage A is green)

- [ ] P10 Smarter, cheaper search
- [ ] P11 Options and money flow

Stage C: operate and decide

- [ ] P12 Forward paper incubation
- [ ] P13 A dashboard that tells the truth, plus project commands
- [ ] P14 Independent audit, then monthly

## The prompts

### P0 · Guardrails, verifier and gap map

Start in plan mode. Today the CI guard only stops the research loop's own identity from touching protected files; Claude Code itself can edit them. This prompt locks the rules in, pauses the search (D11) and sets up a reviewer that didn't write the code.

```text
Follow CLAUDE.md. Read docs/BUILD_PLAN.md in full and AUDIT_REPORT.md. File paths in BUILD_PLAN.md come from the audit; confirm them before editing. This session changes no strategy or research logic. Branch: v2/p0-guardrails.

1. Freeze the search first (BUILD_PLAN D11). Add config flags, read by prometheus/worker.py, that skip the evolution step, the LLM hypothesis and refinement steps, and every submission to the LORD++ gate. Default: paused. Ingestion, options snapshots, paper plumbing and health keep running. Put this in its own small PR so I can merge and deploy it today, then confirm from production logs that the next worker runs skip those steps.

2. Baseline: tag current main as pre-v2-baseline, run the full test suite, and record the result in the Progress log at the end of docs/BUILD_PLAN.md.

3. Laws: append these to CLAUDE.md as Laws 11-20 (renumber if those numbers are taken), leaving every existing law unchanged. For each, say how it is enforced: a test, a hook, a DB rule, or "built in Pn".
   11 Paper only. No code path to any live venue until I tick the go-live checklist by hand; live_trading_enabled stays false.
   12 One ledger. Every backtest for any purpose, including ablations and re-validations, runs through run_trial() and is counted.
   13 Vault sanctity. Time-vault bars, symbol-vault coins and paper-trading results never reach the research loop or any LLM prompt, and Claude Code never uses them to design, tune or rank strategies. Only prometheus/validation/vault.py (one shot per strategy per vault, logged) and paper execution (latest prices, to place orders) read vault data.
   14 Results-based leak defence. Implausible results are quarantined; positions without provenance are rejected.
   15 Blind LLM. Prompts that propose or refine strategies contain no tickers, coin names, dates or years; paper excerpts are passed with those redacted.
   16 Truth tests gate promotion. Red truth tests halt promotion automatically.
   17 Protected files. Claude never edits hard-protected files, and asks me before each edit to an ask-protected file.
   18 Plain English. Every verdict carries one sentence a beginner understands.
   19 Evidence before done. Show real test output. Never weaken a test, threshold or check to get a pass. "No edge found" is a correct result.
   20 Silence is an alarm. Every scheduled job heartbeats; a missing heartbeat alerts me.
   Amend the network rule: allowed are package installs, the data sources our ingestion code uses, and read-only GET requests to our own API (never its holdout or vault data). Never call any broker or exchange trading endpoint.
   Add a "Definition of Done" section: every Done-when item passes with shown evidence; the full suite is green; the verifier agent tried to break the work and failed; a PR is open (never push to main); the phase box in docs/BUILD_PLAN.md is ticked with a three-line evidence note in the Progress log; I get a plain-English report of what changed, what is still open, and what needs my decision.

4. Protected config: create config/protected.yaml. Where a value already lives in config/holdout.yaml or config/costs.yaml, reference it instead of copying it.
   live_trading_enabled: false
   risk: max_position_pct 20, max_gross_exposure_pct 100, max_leverage 1, max_daily_loss_pct 3, max_drawdown_pct 15 (where current env values are stricter, use them; from now on env vars may only tighten these)
   vault: epoch_months 6, epoch_1_start 2026-09-16, epoch_1_evaluation 2027-03-16, symbol_vault_fraction 0.5, symbol_vault_seed (generate one random 64-bit integer now)
   vault_pass_rules: empty for now (P7 proposes them; I copy them in)
   plausibility: max_annual_sharpe 4.0, min_p_value 1e-8, max_hit_rate 0.75 over at least 100 trades, max_months_without_a_losing_month 24
   gate: lord_alpha (copy today's value from the code; don't change it)
   incubation: min_paper_days 182, demote_after_days_below_band 30
   After this session, Claude never edits this file. A later prompt that wants a change writes config/protected.proposed.yaml with its reasons, and I copy values across by hand.

5. Claude Code guardrails in .claude/settings.json:
   - deny Edit and Write on config/protected.yaml and config/holdout.yaml (hard-protected)
   - ask before Edit or Write on config/gates.yaml, tests/laws/**, .github/workflows/**, .claude/** and tools/ci/check_protected_paths.py (ask-protected)
   - deny Read on .env and on any exported holdout or vault data
   - a PreToolUse hook script in .claude/hooks/ that blocks Bash commands that write to hard-protected paths, push to main, force-push, add the owner-approved label, or request holdout or vault market data from our API (keep the blocked-endpoint list in one place so later prompts can extend it)
   Subagents may not inherit project hooks, so repeat the hook in every custom agent's frontmatter. Then prove it: try to edit config/protected.yaml with Edit and with Bash, from the main session and from the verifier agent, and show every attempt blocked.

6. CI backstop: extend tools/ci/check_protected_paths.py so a PR that touches hard- or ask-protected paths fails unless it carries the label owner-approved, which only I add. Add a CODEOWNERS file for those paths. Keep the existing research-loop identity check.

7. Secrets: add a secret scanner (gitleaks or detect-secrets) as a pre-commit hook and a CI job, scan the full git history once, and confirm .env is git-ignored.

8. Verifier agent: create .claude/agents/verifier.md, a skeptical reviewer that did not write the code. Tools: Read, Grep, Glob, and Bash for running tests and read-only queries only. Its job: for a given phase, try to falsify every Done-when claim, writing throwaway tests only in a temp directory; check git diff for weakened tests, thresholds or checks; report PASS or FAIL per claim with evidence.

9. Cleanup: list the untracked dead items from AUDIT_REPORT.md section 2 (root core/, data/ and migrations/, v/, the two garbled C:Users... folders, Mockups.zip, lookAtMe.zip, graphify-out/). Ask me once, then delete them.

10. Makefile targets: test, laws, health and truth (health and truth stay placeholders until P1 and P9).

11. Gap map: write docs/GAP_MAP.md. For each prompt P1-P14, list the existing files it will touch, what already exists, and any conflicts you foresee. Flag anything in BUILD_PLAN.md that is wrong about the code.

Done when:
- production worker runs skip evolution, the LLM steps and gate submissions (show the log lines)
- Laws 11-20 and the Definition of Done are in CLAUDE.md
- config/protected.yaml exists, and blocked edit attempts are shown (Edit and Bash, main session and verifier)
- the protected-paths check fails a simulated PR without the label and passes it with the label
- the full-history secret scan is clean
- the verifier has run once, on this phase
- docs/GAP_MAP.md is written
```

### P1 · Keep it alive and watched

Start in plan mode. Right now nothing checks the system. Railway silently skips runs while a hung one is still going (D9), research may never finish, and the AI refinement step and options recorder have never been seen working. This adds one small always-on Railway service, which costs a little more than cron alone.

```text
Follow CLAUDE.md. Read docs/BUILD_PLAN.md D9 and AUDIT_REPORT.md section 9. Branch: v2/p1-ops.

Part A: find out what is really happening. Evidence only, no fixes yet. Report Part A to me before starting Part B.
1. Why did forced worker runs end exactly when the next cron tick started (15:45 to 16:00, and 16:18 to 16:30)? Railway's docs say overlapping cron runs are skipped, not killed, so look elsewhere: how tools/ops/worker_now.py starts a run (a redeploy?), what the cadence code in prometheus/core does at a tick boundary, container restarts or out-of-memory kills, and the Dockerfile CMD running alembic upgrade head on every start. Use Railway logs (read-only) and the code. State the root cause with evidence, or say it is unconfirmed and list what you ruled out.
2. From the read-only API: the last 50 worker runs, with start, end, concerns run, and whether each finished.
3. Did the first options snapshot land after 21:15 UTC on 2026-09-28? Row counts per underlying and expiry; sanity-check the ATM IV values.
4. Has any llm_refinement hypothesis ever been created in production? If not, find where the step breaks.

Part B: fix and harden.
5. Split work by duration. Cron keeps only short jobs: ingestion, the options snapshot, health. Long research runs on a separate always-on Railway worker service that consumes the existing job queue in prometheus/experiments. Every job gets: a hard timeout, including on every HTTP and Anthropic call, so a hung call can never block later runs; a Postgres advisory lock keyed on the job name; checkpoints so a restarted research job resumes; and a row in a job_runs table (running, succeeded, failed, lost, where "lost" means no heartbeat for twice the expected duration). Migrations run once per deploy, not on every start.
6. Health: add prometheus/ops/health.py and a token-protected, read-only GET /health/summary. Each check is green, amber or red, with one plain-English line:
   - data freshness per source (crypto bars, ETF bars, FRED, options) against its expected schedule
   - the holdout still receiving new bars
   - job_runs: failures, lost runs, research completion rate over 24 hours
   - LLM: outputs in the last 24 hours, and spend against LLM_MONTHLY_BUDGET_USD
   - the search-freeze flags from P0
   - paper engine heartbeat and risk state (P2 fills this in)
   - truth tests (P9 fills this in)
   - database size and growth
7. Alerts: a daily summary at 07:00 Amsterdam time to my alert channel (ALERT_* environment variables, which I will set in Railway), immediate alerts on red, and a ping to HEALTHCHECK_PING_URL at the end of every successful job, so total silence also alerts me.
8. make health prints the same summary locally, from the production API.
9. make pull-snapshot copies research-window data into the local test database: bars before 2026-09-16, excluding symbol-vault coins once they exist. It refuses holdout and vault data; add a law test for that.
10. Using the snapshot, run the audit's missing sanity test (c): the top-scoring strategy with costs doubled over the last 12 months of the research window. Report it in plain English.
11. Verify the AI refinement step end to end with one forced run, tagged purpose=smoke_test and excluded from breeding and the gate (the search stays frozen).

Done when:
- the root cause of the cut-offs is stated with evidence, or marked unconfirmed with what was ruled out
- a test shows a hung job is killed by its timeout, marked failed, and the next run still starts
- a test shows two copies of the same job can't run at once
- a test shows a stale source turns health red and sends an alert (mock channel)
- a production research job completes on the new worker (show the job_runs rows)
- the options snapshot is verified, or its failure found and fixed
- the smoke-test refinement produced a valid, ledger-counted spec in production
- make health output is pasted into the PR
```

### P2 · Risk limits that bite; honest paper accounting

The daily-loss and drawdown limits are loaded but never enforced, nothing caps total exposure, and 13 champions promoted by a broken check are still in the book.

Your decision: item 4 reverses your earlier choice to keep the 13 champions. If you still want them kept, delete item 4 before pasting, but know they were promoted by a check that always passed.

```text
Follow CLAUDE.md. Branch: v2/p2-risk. Files: prometheus/paper/execution.py, broker.py, sim_broker.py, prometheus/core/config.py (RiskLimits), prometheus/worker.py.

1. Enforce every limit in the risk section of config/protected.yaml; environment variables may only tighten them. Checks run before every order and on every mark-to-market:
   - the per-position cap (exists) and a new total gross exposure cap across all strategies
   - daily loss, per strategy and for the whole portfolio, measured from the day's opening equity (UTC): no new orders until the next UTC day
   - drawdown from the equity peak: flatten, halt, and wait for me to re-enable through the existing token-protected admin route
   - every breach sends an immediate alert; KILL_SWITCH keeps working as it does today
2. make kill flattens all paper positions and sets the kill switch.
3. Paper realism: the SimBroker charges exactly the backtest's costs (config/costs.yaml) and fills at the first price available after the signal's data became available (the next bar's open), never at the close the signal saw. Log each fill's slippage against the assumption.
4. My decision: the 13 pre-gate CHAMPIONs become LEGACY_UNVERIFIED, because they were promoted by the always-true DSR check. They stop being breeding parents, open no new positions, and are left out of every leaderboard and scoreboard total. One exception: RANDOM_FOREST-013405 (TRX) keeps paper trading as a plumbing test, labelled "not evidence". Record the change in the append-only history with this reason. They can come back only by passing the full P8 gauntlet like any new strategy.
5. Fix the scoreboard contradiction (it shows "NOT_STARTED - just holding" while a strategy trades): one function computes paper portfolio state, and both the scoreboard and the paper section use it.

Done when:
- simulated price paths trip each limit exactly at its threshold, with the right behaviour and an alert: position cap, gross exposure, daily loss, drawdown
- a test shows environment variables can tighten but never loosen a protected limit
- make kill flattens a seeded test portfolio
- exactly 13 strategies are LEGACY_UNVERIFIED in production (show the query), and a test shows the evolution step never selects them
- the scoreboard and paper section agree in production (show both API outputs)
- the health summary shows risk state
```

### P3 · One honest ledger

Start in plan mode. Ablation backtests aren't counted, there are two ways to run a backtest, the trial count mixes re-validations with new ideas, and nothing protects history from being edited.

```text
Follow CLAUDE.md. Read docs/BUILD_PLAN.md D10. Branch: v2/p3-ledger. Files: prometheus/experiments (runner, ablation.py, lineage.py), prometheus/validation/multiple_testing.py (the COUNT(*) near line 180), the results table.

1. One entry point: run_trial(spec, symbols, window, purpose) is the only way any backtest runs, for any purpose (research, ablation, re-validation, canary, gauntlet sub-test, vault). Route run_one and the ablation harness through it. Add a law test that parses the code (AST) and fails if any other module calls the engine directly.
2. Each ledger row records: spec_hash (canonical family + parameters), trial_key (spec_hash + symbols + window + metrics_version), purpose, code git SHA, data snapshot id, metrics_version, gates_version, proposer (grid, mutation, crossover, llm_hypothesis, llm_refinement, user, canary), parent ids and timestamp. Backfill existing rows where possible and mark unknowns explicitly; never guess.
3. Tamper evidence: every new row stores a hash that chains it to the previous row. A nightly job verifies the chain; a break turns health red.
4. Honest counts, reported three ways: raw trials; distinct strategies (spec_hash per symbol); and the effective number of independent trials, N_eff, estimated by clustering the trials' daily return series (in the spirit of Lopez de Prado & Lewis, 2019; any documented correlation-clustering method is fine). The DSR uses N_eff per search scope (family x asset class), and every report shows all three numbers. Answer the audit's open question: how many of the ~450,600 experiments are distinct strategies?
5. Differential test: write a slow, obviously correct reference backtester (plain Python loops, no polars, about 150 lines) that applies the same rules as prometheus/backtest/engine.py. For 50 random specs across families, equity curves must match the production engine to within 1e-9 relative. Keep it as a permanent test and rerun it whenever the engine changes.

Done when:
- the AST law test fails on a deliberately added direct engine call, then passes once it is removed
- one ablation run increases the ledger by exactly its number of backtests
- the chain verifier catches a hand-edited row in a test database
- raw, distinct and N_eff counts are shown for production, with DSRs recomputed from N_eff in a report (no verdict changes yet; that is P4)
- the differential test passes on 50 specs
```

### P4 · Law 7 first, then fix the score

Start in plan mode. The verdict score includes deflated_sharpe > 0, which is always true, so the top strategies all score 95.385. Your own Law 7 says every past result must be re-checked before thresholds change, and it's still a stub (D5).

Your decision: you approve the threshold change after reading its re-evaluation report.

```text
Follow CLAUDE.md. Read docs/BUILD_PLAN.md D5. Branch: v2/p4-law7-scoring. Files: prometheus/validation/scoring.py (around lines 52-53), multiple_testing.py, tests/laws/test_threshold_global.py (the xfail stub), tests/test_violations.py (the other xfail stub).

Part A: implement Law 7.
1. Move every verdict threshold and scoring rule into config/gates.yaml with a version number (ask-protected).
2. Make verdicts a pure function of stored metrics plus a gates version, and store verdicts append-only with their gates_version.
3. make rethreshold PROPOSED=config/gates.proposed.yaml re-evaluates the whole corpus from stored metrics (no new backtests) and writes docs/rethreshold/<version>.md: how many strategies change status and which ones, plus the null-canary false-pass rate under the old and the new rules. It refuses to finish if the new rules let more null canaries through. After I read the report, I approve the edit to gates.yaml.
4. Replace the xfail stub with a real law test: CI fails if gates.yaml changed without a completed re-evaluation record with the same content hash. Resolve the tests/test_violations.py stub too: implement it, or delete it with a stated reason.

Part B: fix the score through Law 7.
5. Remove the composite 0-100 score and its always-true deflated_sharpe > 0 component. A strategy's standing becomes its status plus its DSR, which ranks strategies within a status. (P8 replaces the statuses with traffic lights.)
6. PBO describes a selection process, not one strategy. Store it on the search batch (family x symbol x window x search run), show it as "chance this batch's winner is overfit", and stop presenting it as a per-strategy number.
7. Run the full cycle: propose, rethreshold, show me the report, wait for my approval, apply.

Done when:
- the Law 7 test passes, and fails when gates.yaml is edited without a record (show both runs)
- the rethreshold report exists and says how many strategies changed status
- no identical 95.385 scores remain; the API and dashboard no longer show a composite score
- PBO appears only at batch level
- the null-canary false-pass rate did not go up
```

### P5 · Catch cheating by its results

Start in plan mode. The audit's oracle scored +22,837 points with p = 0 and the accounting didn't notice (D4). Backtests also fill at the same close the signal saw, which is a small but real optimism.

```text
Follow CLAUDE.md. Read docs/BUILD_PLAN.md D4. Branch: v2/p5-leak-defence. Files: prometheus/backtest/engine.py (run_backtest_from_positions), prometheus/backtest/null_signals.py, tests/laws/test_no_lookahead.py.

1. Provenance: run_backtest_from_positions accepts only positions produced by a registered family generator, carrying a provenance token (family, parameters hash, data snapshot id). Raw position lists are allowed only through an explicitly named test-only function that production code cannot import; add a law test for that.
2. Truncation re-run: for every trial that enters the gauntlet, and a random 1% of all other trials, recompute positions on data cut off at 20 random dates. Every position up to each cut-off must match the full-data run exactly; a mismatch means QUARANTINED plus an alert. Cover all 47 indicator families, the 4 ML families and the 13 rotation families.
3. Plausibility quarantine, using the limits in config/protected.yaml: annual Sharpe too high, p-value too small, hit rate too high over enough trades, too long without a losing month. Quarantined strategies can't be promoted, bred from or shown on leaderboards; they appear on a Quarantine list with the rule that fired.
4. Fill timing: change the engine's default fill from the close the signal saw to the next bar's open plus slippage, matching the paper broker (P2). This changes metrics, so bump metrics_version, recompute metrics for every strategy not already rejected plus all canaries (a background job, with progress shown in the health summary), then run P4's rethreshold so verdicts are re-evaluated by the rules.
5. Oracle bypass test: through the test-only function, feed an oracle that knows each bar's own return (backtest/null_signals.py) and one that knows the next bar's return. Both must be quarantined by result checks alone, with the family system deliberately bypassed.

Done when:
- both oracles are quarantined through the bypass path (show output)
- the truncation check catches a planted leaky family variant (test-only) and passes every real family
- a law test shows production code can't import the raw-positions function
- the metrics v2 recompute has finished, and the rethreshold report says how many strategies changed status because of the fill change
- the P3 differential test still passes with the new fill rule
```

### P6 · Honest data: dead coins included

Start in plan mode. config/universe.yaml lists only today's survivors (no LUNA, no FTT), there are no liquidity limits, and this rebuild supplies the never-seen coins the symbol vault needs (D1).

Your decision: you approve the liquidity-tier cost numbers.

```text
Follow CLAUDE.md. Read docs/BUILD_PLAN.md D1. Branch: v2/p6-universe. Files: config/universe*.yaml, prometheus/data/ingestion.py, loaders.py, quality.py.

1. Prove the source first. Binance's public archive (data.binance.vision: spot daily klines with CHECKSUM files) is reported to keep delisted pairs. Confirm that before relying on it: LUNAUSDT and FTTUSDT history exists and ends where expected, and checksums verify. Check whether our Railway region can reach the archive; if it can't, run the backfill locally and upload. Report to me before building anything else.
2. Staging first: every newly added coin loads into a staging schema the research role cannot read (law test). P7 decides which coins join research and which are sealed in the symbol vault. Until then nothing in the research loop may touch them, so the fresh pool stays fresh.
3. Point-in-time universe: each month, the top 50 spot USDT pairs by trailing 30-day median dollar volume, among pairs with at least 90 days of history on that date. Exclude stablecoins, leveraged tokens (UP, DOWN, BULL, BEAR), wrapped or pegged assets, and fiat or commodity tokens. Store membership as dated rows; nothing uses today's list for past dates.
4. Instrument identity: detect reused symbols and redenominations (for example, LUNA after May 2022 is a different asset; ticker migrations; 1000x contract multipliers). Each becomes a separate instrument with its own dates.
5. Delistings: a position in a coin that stops trading closes at its last traded bar with liquidity-tier slippage. Log every forced exit.
6. Liquidity-tier costs: propose tiers for config/costs.yaml (majors keep 10 + 5 bps; slippage rises as trailing dollar volume falls; below a minimum dollar volume a coin can't be traded). I approve the numbers.
7. Data-quality report in prometheus/data/quality.py: gaps, duplicate bars, zero-volume days, daily moves beyond plus or minus 50%, stale prices, reused symbols. Save it and link it from the health summary.
8. Benchmarks: BTC buy-and-hold; an equal-weight top-10 point-in-time basket (monthly rebalance, same costs); cash; and a world-index ETF (VT, via the existing Yahoo code) converted to euros with FRED's DEXUSEU series. The euro world-ETF line is the headline benchmark for my money.
9. Bars dated 2026-09-16 or later for every new coin go to the holdout schema, like today's coins.

Done when:
- dead-coin coverage in the archive is proven (LUNA and FTT evidence)
- a law test shows the research role can't read staging coins
- a law test shows universe membership on any past date uses only data available then
- symbol-reuse detection catches the LUNA case in a test
- the data-quality report is produced and linked from the health summary
- you report how many new coins appear in zero ledger trials (the pool for the symbol vault)
```

### P7 · The vault, rebuilt

Start in plan mode. This is the audit's biggest finding: the one-shot holdout function exists but nothing calls it, and the holdout is 12 days long. This prompt builds D1, the out-of-sample p-value from D2, and D7.

Your decision: you copy the proposed pass rules into config/protected.yaml yourself.

```text
Follow CLAUDE.md. Read docs/BUILD_PLAN.md D1, D2, D6 and D7. Branch: v2/p7-vault. Files: prometheus/validation/holdout.py (access_holdout, access_holdout_for_paper), config/holdout.yaml, the evaluator-isolation migration (0024), tests/laws/test_evaluator_isolation.py, the vault section of config/protected.yaml.

1. Symbol-vault assignment: from the P6 staging pool, take the coins that appear in zero ledger trials. Assign symbol_vault_fraction of them to the vault using symbol_vault_seed, deterministically, stratified by listing year so both halves span the same market eras. Write the assignment once into a write-once table (database rules block UPDATE and DELETE). Release the other half to the research universe.
2. Database access control: the research role cannot SELECT symbol-vault bars, holdout bars or paper-trading results. Extend tests/laws/test_evaluator_isolation.py to prove it table by table. Paper execution keeps its own narrow access for placing orders.
3. prometheus/validation/vault.py becomes the only reader. evaluate(strategy_id, vault), where vault is "symbol" or "time":
   - requires a frozen, pre-registered spec with a timestamp, and a recorded Stage-1 pass (P8 builds Stage 1; until then evaluate() refuses everything, which is correct)
   - refuses a second test of the same spec_hash on the same vault, and refuses any strategy with a vault_failed_ancestor flag set in the last 12 months
   - symbol vault: runs the frozen spec on each vault coin over the research window (on the vault universe for cross-sectional strategies), measures excess over the strategy's exposure-matched random twins (D3; P8 builds the twin generator, so stub it until then), and combines the coins into ONE p-value with a time-block bootstrap that resamples the same dates across all vault coins, so correlated coins don't count as independent evidence
   - time vault: runs once per strategy on the epoch's evaluation date, on that epoch's dates, using the pass rule pre-registered in config/protected.yaml
   - logs every access append-only (who, when, strategy, vault, result) and returns only pass or fail plus summary statistics, never vault price series
   - a failure sets vault_failed_ancestor on every descendant, using the lineage table
4. Epochs: epoch 1 runs from 2026-09-16 to 2027-03-15 and is evaluated on 2027-03-16. At each close, every eligible frozen strategy is evaluated once, then the epoch's data is released into the research window and the next epoch opens. The release is a job with a dry-run mode that I trigger.
5. Pass rules: write proposals to config/protected.proposed.yaml with a plain-English explanation. Suggested defaults. Symbol vault: LORD++ decides on the combined p-value, and in addition the median vault coin must beat its twins and at least 60% of vault coins must show positive excess. Time vault: pass if the bootstrap 95% lower bound of excess over twins is above zero, or if the excess is positive, the Sharpe is at least half its research-window value, and IC keeps its sign. vault.py refuses to run until I have copied the rules into protected.yaml.
6. Close the leaks: the evolution loop, LLM packets, leaderboards and parent selection can't read paper-trading results (law test). make pull-snapshot and every API endpoint the P0 hook allows exclude vault-period market data and symbol-vault coins (law test). Remove or reroute the unused access_holdout so there is exactly one way in.
7. API data for the dashboard: symbol-vault tests used, strategies waiting, days of epoch data so far, next evaluation date.

Done when:
- law tests prove the research role can't read vault coins, holdout bars or paper results
- a second evaluate() on the same spec is refused, and so is a descendant of a failed strategy
- on a synthetic panel of highly correlated null coins, the combined symbol-vault p-value is uniform (false-pass rate at alpha within simulation error)
- the epoch-release dry run lists exactly which dates would move
- the assignment table rejects UPDATE and DELETE
```

### P8 · Gauntlet v2 and an honest re-run

Start in plan mode. The audit found no 2× cost stress, no plateau test and no delay test, a walk-forward that can't test anything for strategies without fitted parameters, and a gate spending its budget on in-sample p-values. This is where the pieces come together. Nothing is sent to the vaults yet; that waits for the truth tests in P9.

Your decisions: the mapping from old statuses to new ones, and whether LORD++ needs a variant that tolerates dependent p-values.

```text
Follow CLAUDE.md. Read docs/BUILD_PLAN.md D2, D3 and D10. Branch: v2/p8-gauntlet. Files: prometheus/validation/* (discovery_gate.py for LORD++, regime.py, decay.py, splits.py, promotion), the prometheus/api status routes.

Build the gauntlet as ordered gates. Every gate returns {passed, value, threshold, reason_plain}. All thresholds live in config/gates.yaml, and every change goes through rethreshold (P4).

Stage 1 uses research coins and the research window only. Cheapest gates first; stop at the first failure but record everything computed.
G1 Integrity: provenance, truncation re-run and plausibility (P5).
G2 Timing skill (D3): 1,000 exposure-matched random twins, built by shuffling the order of the strategy's own in-market and flat spells on the same coin (same exposure, same number of trades, same costs). Pass if it beats at least 95% of them. For rotation and cross-sectional families, twins pick at random from the same eligible set on the same schedule. Excess over buy-and-hold stays as a reported number, not a gate.
G3 Signal quality: IC and ICIR at the pre-registered horizon; half-life from the IC decay curve; fail as "short-lived" if the half-life is under 5 bars or the edge after costs is zero or negative at every rebalance frequency.
G4 Cost stress: excess still positive at 2x costs, with the P6 liquidity tiers.
G5 Delay: keeps at least 50% of its excess with one extra bar of delay.
G6 Plateau: nudge every numeric parameter by plus or minus 10% and 25% (all combinations, capped); pass if at least 70% of neighbours keep at least 50% of the excess. Save the heatmap.
G7 Walk-forward of the whole selection process: in each fold, rerun the selection procedure that produced this strategy (its family's grid and ranking rule) on the training years only, take that winner, and score it on the next year. Pass if at least 60% of test years are positive and the average test IC keeps its sign. For AI-proposed strategies, use the family grid as the stand-in procedure. This tests the method, not only the pick, and answers the audit's question about CPCV folds for strategies without fitted parameters.
G8 Regime: no regime with Sharpe below -1 where there are enough days; record the regimes where it works.
G9 Statistics: DSR using N_eff (P3) of at least 0.95; a stationary-bootstrap 95% interval for excess Sharpe; 5,000 Monte Carlo reshuffles of trade order giving the 5th-percentile max drawdown and the longest losing streak in plain English; the batch PBO reported with a warning above 0.5 (not a gate).

Stage 2 spends scarce resources, in this order (build it now, but send nothing through it until P9):
G10 Symbol vault (P7), which produces one out-of-sample p-value.
G11 LORD++ on that p-value. Continue the existing sequence and never reset alpha-wealth. LORD++'s guarantee assumes independent p-values, and ours come from overlapping data. Check the implementation and the literature on dependence-robust online testing, and report to me before changing anything. The decision is mine.
G12 Time vault at the epoch close (P7).

Traffic-light statuses, each with a one-sentence plain-English reason:
GRAVEYARD (black): failed a gate; say which and why.
PROMISING (yellow): passed G1-G5.
ROBUST (orange): passed G1-G9.
DISCOVERED (green): passed G10 and G11; may start paper incubation.
VALIDATED (blue): also passed G12.
LIVE_ELIGIBLE (star): set only by me, through the go-live checklist.
Propose how the existing statuses (REJECTED, REGIME_SPECIALIST, PROMISING, QUARANTINED, DORMANT, VALIDATED, CHAMPION, LEGACY_UNVERIFIED) map onto these, and wait for my approval.

The re-run:
- Put every non-rejected strategy, plus the 13 legacy ones, through Stage 1, reusing stored metrics where still valid.
- Survivorship report: rerun 20 existing strategies on the old survivor list and on the point-in-time research coins over the same dates, and say in plain English how much the survivor list flattered or hurt results.
- Add an uncapped status-count endpoint (the current list stops at 500 rows).
- Write docs/leaderboard_v2.md: counts per status, the graveyard grouped by the gate that killed each strategy, and a plain-English summary.

Done when:
- the random 50/50 canary dies at G2 or earlier
- a long/flat rule on a synthetic coin that falls 80% beats buy-and-hold but fails G2
- both oracles die at G1
- the best of 500 random parameter sets for one family fails at G6, G7 or G9
- every status change went through rethreshold
- docs/leaderboard_v2.md is written, with Stage 1 results only; nothing has been sent to Stage 2
```

### P9 · Truth tests: the system proves itself every night

This is what "100% works" means in practice. Canaries already test the pipeline; truth tests measure the gate's error rate and its power every night, and halt promotion if either drifts. Only after three green nights does anything go to the vaults, and only then does the search restart.

```text
Follow CLAUDE.md. Read the section "What 100% works can honestly mean" and D10 in docs/BUILD_PLAN.md. Branch: v2/p9-truth. Files: prometheus/validation/canaries.py, prometheus/backtest/null_signals.py, worker scheduling, prometheus/ops/health.py.

Build a nightly truth-test job (make truth runs it locally). It pushes known-answer strategies through the real gauntlet, with Stage 2 simulated on synthetic coins (never the real vaults), all counted in the ledger with purpose=canary.
1. Nulls: 200 random-signal strategies on research data and on synthetic random walks. Expected: a Stage-1 pass rate no higher than the error rate set in gates.yaml (default 5%), and none reaching DISCOVERED in the simulated Stage 2.
2. Oracles (same-bar and next-bar, through the test-only path): expected 100% quarantined at G1.
3. Falling coin: long/flat rules on a synthetic coin that falls 80%. Expected to beat buy-and-hold and fail G2.
4. Planted edges (power): synthetic markets with a true edge of annual Sharpe 0.5, 1.0, 1.5, 2.0 and 3.0, judged with production's N_eff and Sharpe variance so the power matches reality. Report the detection rate at each size. The smallest size detected at least 80% of the time is the "minimum detectable edge".
5. Delay: a slow true edge survives G5; a leaky fast one fails.

Store daily: a confusion matrix (false passes, missed plants, oracle catches), the power curve and the minimum detectable edge. The result is red if nulls pass above the error rate, any oracle slips through, the falling-coin canary passes, or power at Sharpe 3.0 drops below 80%. Red triggers an automatic promotion halt (reuse the existing halt and its token-protected clear route) and an alert.

Add one plain-English line to the daily alert, for example: "Truth tests green. Right now the system can reliably spot an edge of Sharpe X or bigger; smaller real edges would be missed."

After three consecutive green nights:
- send up to 20 ROBUST strategies through Stage 2 (symbol vault, then LORD++): the best by DSR, at most one per family niche; if none are ROBUST, send nothing and say so
- lift the P0 freeze on the evolution step and gate submissions; the AI steps stay frozen until P10
- update docs/leaderboard_v2.md with the Stage-2 results

Done when:
- one full truth run has completed in production, with results in the health summary
- deliberately breaking G2 on a test branch turns the truth tests red and halts promotion
- three green nights are recorded, Stage-2 results are in the leaderboard, and every vault access is logged
```

### P10 · Smarter, cheaper search

Start in plan mode. The loop currently breeds from the broken champions, has no diversity archive or budget stop, and its AI prompts could steer from memory (D6). Nobody measures whether the AI beats random mutation, which matters because you pay for it.

```text
Follow CLAUDE.md. Read docs/BUILD_PLAN.md D6, D7 and D10. Branch: v2/p10-search. Files: prometheus/worker.py (_run_evolution_step, _run_llm_refinement_step), prometheus/research/population.py, mutations.py, crossover.py, research/llm/refinement.py, hypothesis.py, budget.py.

1. Parents come only from ROBUST strategies, plus 20% from PROMISING strategies that failed exactly one Stage-1 gate. Never LEGACY_UNVERIFIED, QUARANTINED, or anything whose standing depends on vault or paper results.
2. Diversity archive (MAP-Elites): keep the best strategy per niche, where a niche is family x horizon bucket x regime where it works x asset class, so the population can't collapse into copies of one idea.
3. Blind prompts (D6): the refinement and hypothesis prompts say "Asset A" and "period 1...n" instead of coin names and years, and paper excerpts have tickers and years redacted. Include the failing gate and its reason, IC by period, the decay curve, the plateau summary, and the five most similar graveyard strategies with why they died. Never vault or paper results. Law test: any strategy prompt containing a ticker, coin name, date or four-digit year fails.
4. One self-correction retry for an invalid spec; every attempt counts in the ledger.
5. Budget stop (D10): track the evaporation curve (best Stage-1 DSR against trial count). When the bar has risen faster than the best candidate for K rounds (K in gates.yaml), stop the loop and alert me: "more searching is now hurting more than helping". Add hard daily caps on trials and AI calls.
6. Is the AI helping? Split children 50/50 between AI proposals and random mutations of the same parents. For each arm, track how many per 1,000 trials reach PROMISING and ROBUST, with confidence intervals, on the dashboard. If after 2,000 trials per arm the AI arm isn't better, say so plainly in the daily alert so I can decide whether it's worth paying for.
7. Calibration: the AI already states a prior_probability for each hypothesis. Score those against outcomes (Brier score and a reliability table), the way the phil project scores its own calibration.
8. New seed families that the point-in-time universe now allows, each pre-registered with its paper as the source: cross-sectional crypto momentum (Liu, Tsyvinski & Wu, 2022, found market, size and momentum factors in crypto returns). Add size only if you can find free point-in-time market-cap data; otherwise say so. They enter through the gauntlet like everything else.
9. Lift the P0 freeze on the AI steps.

Done when:
- the blind-prompt law test passes, and fails on a planted prompt containing "ATOM" or "2022"
- a test shows LEGACY_UNVERIFIED and QUARANTINED strategies are never chosen as parents
- the budget stop fires in a simulated run where the bar outpaces the best candidate
- the AI-versus-random panel shows live numbers
```

### P11 · Options and money flow

Start in plan mode. This is the "follow the big money" module from the first plan, built the honest way: raw data saved from now on, history from DoltHub, and output framed as "where to look", never as a buy signal (D8).

```text
Follow CLAUDE.md. Read docs/BUILD_PLAN.md D8. Branch: v2/p11-options-flow. Files: prometheus/data/providers/cboe_options.py, the options_daily table, ingest_etf.py, the family registry.

1. Raw chains from today: store every daily CBOE snapshot per contract (underlying, expiry, strike, call or put, bid, ask, last, volume, open interest, IV and greeks when given, snapshot time, available_at), compressed, alongside today's aggregates.
2. History: DoltHub's post-no-preference/options database (tables option_chain and volatility_history; the branch is master, not main; its SQL API needs no key or account). First inspect the schema and the coverage for our 11 sector ETFs plus SPY and QQQ, and write a short coverage report. Load only research-window dates (before 2026-09-16) into research tables with source='dolthub'. Don't invent fields; flag gaps.
3. Derived daily metrics per underlying: 30-day at-the-money IV; 25-delta put IV minus at-the-money call IV (the Xing-Zhang-Zhao smirk); matched-strike call-put IV spread (Cremers-Weinbaum); put/call volume and open-interest ratios; IV minus 20-day realised volatility; IV change. Compute IV yourself with a standard model when the source's value is missing or absurd; drop zero-bid contracts and absurd spreads.
4. Sector money flow for the 11 sector ETFs: relative strength against SPY over 5, 20 and 60 days; 20-day Chaikin Money Flow; dollar volume against its 60-day average; changes in put/call ratio and smirk. Combine them into a z-scored Flow Score with one plain sentence per sector, for example "Energy: rising price, heavy volume, options traders turning bullish". Add a divergence scanner for |z| > 2 whose cards say "worth a look, NOT a buy signal".
5. New families, each with look-ahead law tests: SECTOR_FLOW_ROTATION, OPTIONS_SMIRK_TIMING, CP_SPREAD_TIMING, PRICE_OPTIONS_DIVERGENCE. A signal built from a snapshot taken at 21:15 UTC trades at the next session's open, never the same day.
6. Our own snapshots from 2026-09-28 onward are epoch-1 data: the research loop can't read them until the epoch closes (law test). The morning report may show them to me, but Claude Code sessions don't read it; add its endpoint to the P0 hook's blocked list.
7. History badge: any options family with under two years of research-window history is marked "not enough history to judge yet" and can't go beyond PROMISING.
8. Morning report: an API route and a dashboard page, generated after the US close, in under five minutes.

Done when:
- raw chain rows accumulate daily (show counts for three days)
- the DoltHub coverage report is written, and the backfill is loaded for whatever exists
- derived metrics match hand calculations on a toy chain (test)
- the new families pass look-ahead law tests and run through the gauntlet
- the morning report renders with plain-English cards
```

### P12 · Forward paper incubation

Paper trading on days that haven't happened yet is the only test nothing in the system could have seen, including Claude's own memory of market history. This turns it into a measured experiment instead of a scoreboard.

```text
Follow CLAUDE.md. Read docs/BUILD_PLAN.md D7. Branch: v2/p12-incubation. Files: prometheus/paper/*, prometheus/worker.py.

1. Two books with separate accounting, reported in euros: long_term (ETF rotation families, monthly rebalancing; benchmark: the euro world-ETF line from P6) and crypto (crypto families; benchmarks: BTC buy-and-hold and the equal-weight top-10 basket). A "just hold the benchmark" position runs in each book as a permanent comparison.
2. Only DISCOVERED and VALIDATED strategies incubate. Equal risk across them, capped by config/protected.yaml.
3. Expected band: from each strategy's research-window returns, simulate the range of cumulative returns over the next N days with a block bootstrap. Each day, place the strategy's actual paper result inside that band.
4. Daily retrospective after the close: per strategy, "on track", "below expectations" or "broken"; realised slippage against assumed costs; one plain-English line. Auto-demote to GRAVEYARD, with the reason, after 30 trading days below its 5th-percentile band.
5. Paper results still never feed research (the P7 law tests must still pass).
6. Live-eligibility report per strategy: days incubated, band position, excess over its benchmark after costs in euros, realised-to-assumed cost ratio, time-vault result, and the minimum track record length (Bailey & Lopez de Prado) needed to confirm its Sharpe from paper data alone. State that honestly, for example: "Confirming this edge from paper results alone would take about X years; six months only checks that it behaves as expected."

Done when:
- a seeded test strategy walks through incubating, on track, and auto-demoted on a synthetic bad path
- both books report in euros with benchmark lines
- the retrospective appears in the daily alert
```

### P13 · A dashboard that tells the truth, plus project commands

The current dashboard ranks raw best-of-450,000 in-sample results and shows a score that was always inflated. A beginner should be able to open it and know within ten seconds whether anything is working.

```text
Follow CLAUDE.md. Branch: v2/p13-dashboard. Files: frontend/src/dashboard/*, app/page.tsx, prometheus/api routes. Keep the pixel world.

Every number gets a hover tooltip and a plain-English sentence. Traffic-light badges everywhere. No composite score anywhere. Any number measured on the data a strategy was chosen on carries the label "in-sample: measured on the data it was picked from".

Pages:
1. Home: three questions answered in words. Is anything working? Is my paper money beating just holding the index (in euros)? What changed today? A red banner whenever health or truth tests are red.
2. Honesty meter: raw, distinct and effective trial counts; the DSR bar against the best candidate over time (the evaporation curve); LORD++ alpha-wealth and next threshold; the truth-test confusion matrix, power curve and minimum detectable edge; symbol-vault tests used; days until the next epoch evaluation.
3. Leaderboard by status (sorted by DSR within each status), the graveyard grouped by the gate that killed each strategy, and the quarantine list.
4. Strategy detail: the gauntlet checklist with each gate's plain reason; equity against its random-twin band and buy-and-hold; IC decay with half-life; plateau heatmap; walk-forward bars; regimes; Monte Carlo drawdown fan; lineage.
5. Family tree coloured by status; Incubation (actual against expected band); Morning money flow (P11); Health.

Project commands as Claude Code skills in .claude/skills/. Check `/` for name collisions first: /loop is already built into Claude Code, so give every command a prom- prefix.
- /prom-status: five plain sentences on what's working, from the API.
- /prom-explain <strategy_id>: a plain-English deep dive, including its family tree and why each gate passed or failed.
- /prom-new-strategy <description>: translate my words into a StrategySpec using only existing families. If that's impossible, say so and offer the closest version. Show me the plain-English explanation and what it will be compared against, then wait for my yes. Then pre-register it (source=user), run the gauntlet, and report the traffic light with a one-line reason plus two or three suggested next experiments.
- /prom-health: the health summary.
- /prom-audit: a placeholder that P14 completes.

Done when:
- every page renders with production data (screenshots in the PR)
- the P2 scoreboard and paper consistency test still passes
- each command has run once successfully
```

### P14 · Independent audit, then once a month

The first audit was a self-audit by the session that wrote most of the code. This one is done by a fresh session plus the verifier agent, and it trusts nothing without evidence. If you can, switch Claude Code to a different model from the one that did most of the building (/model) before pasting this.

```text
Fresh session. Don't trust docs/BUILD_PLAN.md ticks, PR descriptions or earlier reports; check the code and the running system. Use the verifier agent for each area. Read-only, except for the new report file.

Try to break each of the seven guarantees in docs/BUILD_PLAN.md:
1. Future information: plant leaky variants (temp directory, test-only paths) and confirm G1 or a law test catches each one.
2. Counting: look for any backtest path that bypasses run_trial, and verify the ledger hash chain on production data.
3. False passes: rerun the null truth tests with a new seed and compare with the stored rates.
4. Power: confirm the minimum detectable edge is computed from the current N_eff.
5. Vaults: try to read vault coins and holdout bars through every endpoint Claude Code can reach; try to read paper results as the research role; try a second vault shot; check the vault access log against strategy statuses.
6. Risk: replay a simulated crash through paper execution.
7. Silence: stop a job in a test environment and confirm that both the alert and the dead-man's switch fire.
Then re-check every red flag in section 4 of AUDIT_REPORT.md and mark each one fixed, not fixed, or regressed.

Write docs/AUDIT_<date>.md: a plain-English verdict first, then one table per guarantee with evidence. Nothing counts as fixed without evidence.

Finally, complete the /prom-audit skill so it repeats this audit and compares the result with the previous audit, listing regressions first. I'll run it monthly.
```

## Go-live checklist (you tick it; the system never does)

These prompts never build live trading. If one strategy clears everything below, building a live connection is a separate, deliberate project.

- [ ] The strategy is VALIDATED: it passed the symbol vault and the time vault on its first and only try, and LORD++ counted it as a discovery.
- [ ] It has at least six months of paper incubation inside its expected band, beating its benchmark after costs, in euros.
- [ ] Truth tests have been green for the last 30 days, and the latest independent audit is clean.
- [ ] You can explain in one sentence why it should work.
- [ ] You start with a small, capped amount you can afford to lose completely, with limits in config/protected.yaml.
- [ ] Real fills cost no more than about 1.5× the assumed costs, checked on a tiny first live test.
- [ ] Your broker or exchange is authorised to serve Dutch residents (check the AFM register) and supports API trading for your account type.
- [ ] You've checked how Box 3 tax applies to you.

## What to expect

The most likely outcome, given 0 discoveries in 102 gate tests and the August 2026 study from the first plan, is that most or all of today's candidates end up in the graveyard after P8, and the system tells you the best home for real money is the world index. That is a real and valuable answer, and after these prompts the system will have earned the right to give it.

The rough timeline: Stage-1 verdicts after P8; symbol-vault verdicts, for any strategy that reaches ROBUST, within days of P9 going green; the first time-vault verdicts on 16 March 2027. A strategy discovered in the next few weeks and incubated through the epoch could meet the six-month paper rule in spring 2027 at the very earliest.

One number deserves your attention: the minimum detectable edge from P9. If it says the system can only see edges of Sharpe 2 or more, then "nothing found" means "nothing big found", not "nothing exists". That number falls slowly as each epoch adds data, and it rises with every extra search, which is why the budget stop in P10 matters.

## Progress log

Claude Code adds dated entries here: the prompt, the PR link, and a three-line evidence note.

Baseline (P0, 2026-09-29): tag `pre-v2-baseline` = `12d54dd` (main on
2026-09-28; the audit was on `70a8e96`, and `12d54dd` adds the one-shot vault
test, the pre-gate re-test and per-strategy paper loss limits; see
docs/GAP_MAP.md). Full suite on a fresh Postgres at that commit: 1178 passed,
1 skipped, 2 xfailed (both `xfail(strict=True)` stubs: Law 7 and
tests/test_violations.py).
