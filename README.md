**English** | [한국어](README.ko.md)

# AIPOL

**An open-source policy-making support project that uses AI while keeping decisions with people.**
We develop a methodology, a research engine, and field tools together so that complex policy issues
can be examined from multiple perspectives, alternatives can be compared, and human approval and
judgment can be kept as a reproducible record. The project is not tied to any particular policy area.

Pension reform is the **first application (Application 01)**. The public repository holds only
reusable policy-development contracts and tools; event run sheets, meeting materials, unpublished
policy proposals, and raw research data are managed in a private repository.

> **Canonical repositories:** [`nextain/aipol`](https://github.com/nextain/aipol), which you are
> looking at now, is the canonical home of the public framework, the site, and reproducible
> aggregates. The canonical home of the actual pension event app and of private research and
> operations material is `apps/pension-policy-lab/` in the private `nextain/aipol-lab`.
> `nextain/pension-policy-lab` and `armybonita/Pension-Policy-Lab-` are past history and are no
> longer used for changes or deployment. For the detailed boundary and how to take part, see
> [`docs/repository-boundary-and-contribution.ko.md`](docs/repository-boundary-and-contribution.ko.md) (Korean).

The project started while preparing a pension-reform policy experiment. We are growing the
policy-development methodology, research engine, online and on-site participation tools, and
verification records developed here into an open-source shared research base that other policy
areas can use as well.

## New here?

| What you want to do | Where to go |
|---|---|
| Understand the project in 3 minutes | [Public introduction site](https://aipol.kaps.or.kr/project/) |
| See the first case | [Pension reform case](https://aipol.kaps.or.kr/cases/pension/) |
| Check the structure in code | The [domain-neutral engine](#2-domain-neutral-engine--safeguards--policy_lab) below · [`examples/quickstart.py`](examples/quickstart.py) |
| Contribute to docs, evidence, or code | The five first-contribution steps in [`CONTRIBUTING.md`](CONTRIBUTING.md) (Korean) |
| Take part with Codex or Claude | [How to start with each AI tool, and the public boundary](docs/repository-boundary-and-contribution.ko.md) (Korean) |
| See the 250-participant performance test | [JMeter + Chromium measurement report](docs/performance/jmeter-playwright-250-participants-2026-08-14.ko.md) (Korean) |
| Check public event information | [Event information](https://aipol.kaps.or.kr/events/) |

## Public site

The source of the public introduction site is in [`site/`](site/). It explains, each on its own
page, the project's purpose, how it works, the platform, its trust principles, how to take part in
the open source project, and the pension-reform application. It is now publicly live, so anyone with
the URL can view it. The public introduction pages allow search indexing, while the actual survey and
facilitator screens are kept separate on a different domain with a `noindex` response header. For the
detailed operating contract, see [`site/README.md`](site/README.md) (Korean).

- Public address: <https://aipol.kaps.or.kr>
- English: <https://aipol.kaps.or.kr/en/>
- Global AI policy-making trends RSS: <https://aipol.kaps.or.kr/global/rss.xml>

## Policy News Bot

`bots/policy_news/` is a collector that finds candidate material on AI-based policy development in
official feeds from governments and international organizations. The 8 items published so far were
researched and edited by Codex directly from the official originals; the exact underlying model
version used at the time was not recorded. Upstage `solar-open2` completed an authenticated call and
generated one private draft, but that draft was not published because it duplicated existing
material. For OpenRouter `nvidia/nemotron-3-ultra-550b-a55b:free` source cross-checking and scheduled
automatic publishing, every day at 6 a.m. (KST) the bot collects up to 3 items from official sources
and records a Solar Open2 draft and a Grok 4.3 source cross-check result in a private repository.
There is no automatic publishing to the public; publishing requires human review and a separate pull
request. The operating boundary is recorded in [`bots/policy_news/README.md`](bots/policy_news/README.md) (Korean).

---

## What we built

This repository has two layers. One is **the tool that runs actual events**; the other is the
**domain-neutral engine and safeguards** underneath it.

### 1. Event facilitation tool — `event-tool/`

A policy deliberation tool that a single facilitator runs live. It collects citizens' responses to
expert proposals, gathers them without omission so that AI can propose additional options, lets
people review and approve before re-collecting in the next round, and carries through to the final
report. Pension is the first case, but by swapping only the data (the case) it can be reused for
other policies.

- **Citizen screen** (mobile and accessibility for older users first): accept / conditional / reject
  per proposal, plus comments.
- **Facilitator screen**: step by step through prepare → collect → AI deliberation → revise and
  approve → next round → report.
- **AI deliberation**: three Korean sovereign LLMs (EXAONE, Solar, HCX) cross-review in 6 stages to
  produce a combined proposal; guards block self-reinforcement and false precision, and what was and
  was not reflected is shown honestly.
- **Stack**: FastAPI + SQLite + plain HTML/CSS/JS. Supports local runs and single-author Azure
  deployment.

For how to run it and the detailed operating flow, follow [`event-tool/README.md`](event-tool/README.md) (Korean).

> **Distinction:** `event-tool/` in this section is a public, general-purpose reference
> implementation. The pension participant, admin, and results apps currently at
> `session.aipol.kaps.or.kr` are not deployed from this directory; their canonical source is the
> private `nextain/aipol-lab:apps/pension-policy-lab/`. Using the public tool to collect from real
> citizens requires separate authentication, a managed database, backup and recovery, personal-data
> retention and disposal, and operational approval.

```bash
cd event-tool
python3 -m venv .venv && .venv/bin/pip install fastapi uvicorn
.venv/bin/uvicorn server:app --host 127.0.0.1 --port 8100
# Citizen http://127.0.0.1:8100/   ·   Facilitator http://127.0.0.1:8100/admin.html
```

To use AI deliberation, put the Dokpamo (Korean sovereign AI foundation model) API key in `.env` (never commit it). Prepare, collect, and report
work without a key.

### 2. Domain-neutral engine + safeguards — `policy_lab/`

The **framework and safety mechanisms** underneath the event tool. It expresses policy debate
experiments in code and uses safeguards to stop those experiments from fooling themselves. It is
closer to a checking tool (linter, type checker) for policy experiments: when a design breaks a rule,
it raises `GuardViolation` and rejects it.

| What | Substance |
|---|---|
| **Safeguards** `core/guards.py` | Single-number rejection · human_gate · A/B separation · variable whitelist · protocol invariants |
| **Deliberation protocols** `core/protocols.py` | Reusable stage graphs and `validate()` |
| **Data model** `core/{levers,evidence,impact,deliberation,provenance,prompts,plugin}` | Representation of levers, evidence, impact, votes, and reproduction logs |
| **Pension domain** `domains/pension` | Levers, fixed variables, evidence anchors, directional impact model, prompts, segments |

```bash
pip install -e ".[test]"
pytest -q     # verifies that the safeguards actually block
```

> **How the two layers relate (honestly):** `event-tool/` is an independent lightweight
> implementation built for the 8/12 event, and it enforces the guard concepts fail-closed in its own
> code (it does not currently import the `policy_lab/` core directly). `policy_lab/` is the
> domain-neutral SoT framework. Unifying the guard code of the two layers is follow-up work.

## What it is, and what it is not

- **What it is:** a framework that uses AI as a *tool* to structure, record, and verify the process
  in policy debates where human experts and the audience are the main actors.
- **What it is not:** a system in which AI decides policy, predicts public opinion, or produces the
  "right answer" policy.

## Design identity (why we built it this way)

The safeguards are not empty promises; they enforce the following principles in code (RFC §6).

1. **A/B methodological independence** — The deterministic impact model (A) and the public
   deliberation loop made of human statements (B) are kept separate, so errors are not amplified in
   a closed loop. (The event tool does not handle a numerical impact model, so it has no A; instead,
   a single-number ban guard blocks claims of quantitative authority.)
2. **AI is a tool that helps the debate, not an oracle** — The goal is always people.
3. **Reproducibility** — Model, version, temperature, seed, and prompt are all recorded.
4. **Falsifiability** — Pre-registered holdouts and an external panel are core concepts.
5. **Transparency** — Prompts, evidence sources, and calculation assumptions are published.
6. **Exposing framing power** — Agenda setting and issue selection go through an approval gate by
   human experts.
7. **Offline fallback (planned)** — Preparing to run without the internet using a local model (naia).

## What is not there yet (honestly)

- **Guard unification between event-tool and the `policy_lab/` core** — currently each layer
  implements guards separately.
- **Full undo/resume · improved presentation mode · rehearsal mode · complete per-object CRUD** —
  postponed until after the event.
- **A local-model operating path** — AI deliberation currently depends on the external Dokpamo API
  (key and network).

## Structure

```
aipol/
  README.md
  RFC-0001-framework.md         ← domain-neutral architecture (SoT)
  RFC-0002-deliberation-runner.md
  event-tool/                   ← live event facilitation tool (FastAPI+SQLite+web)
  site/                         ← static public site introducing the whole project
  bots/policy_news/             ← official global-trend candidate collection · Codex editing queue
  content/global-ai-policy/     ← reviewable structured global-trend content
  policy_lab/
    core/                       ← safeguards + data model + protocols
    domains/pension/            ← first reference implementation
  tests/                        ← pytest (safeguard verification)
  private/                      ← local-only run records (not tracked; use the private repository)
  examples/quickstart.py        ← one-minute library example
  docs/                         ← design docs · evidence (adversarial review)
```

## Status

We have implemented the design (RFCs), the domain-neutral core and pension domain, the safeguards,
the live event tool (event-tool), and the public introduction site. The on-site pension-reform policy
experiment was carried out on August 12, 2026. The operational participant app is managed in the
private `nextain/aipol-lab`; this public repository reflects only generalizable methods, code, and
de-identified aggregates. On August 14, 2026, we completed a performance test over the public external
path with 250 JMeter sessions and 250 real Chromium instances. Repository:
<https://github.com/nextain/aipol>. License: Apache-2.0.
