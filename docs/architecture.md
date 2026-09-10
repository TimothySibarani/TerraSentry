# Architecture

## The shape of the problem

Input: a company name and a patch of land, often incomplete.
Output: an evidence dossier that survives an auditor.

Nothing here needs predicting. Every input already exists in public data. The work is
**evidence assembly** under uncertain inputs, plus one judgement call at the end:
*is this enough to sign a legal statement?*

## Layers

```
        +------------------------------------------------+
        |  SAP Joule  ·  RIMBA reasoning panel            |   interface
        +----------------------+-------------------------+
                               |
        +----------------------v-------------------------+
        |  Orchestrator (Bedrock Converse loop)           |   decides WHICH tool
        |  agent/orchestrator.py                          |   and WHEN to stop
        +----------------------+-------------------------+
                               | tool calls
   +----------+----------------+---------------+----------------+
   v          v                v               v                v
geometry  forest_change      firms          entity        verify_permit
(gate)   (technical core)  (easy win)    (synthetic)        (registry)
   +----------+----------------+---------------+----------------+
                               v
        +------------------------------------------------+
        |  scoring.py   deterministic rubric              |   NO MODEL HERE
        |  evidence.py  citation ledger                   |
        +----------------------+-------------------------+
                               v
        +------------------------------------------------+
        |  dds.py  ->  TRACES-aligned draft OR gap list   |
        +------------------------------------------------+
```

## Division of responsibility

| Layer | Decides | Does not |
|---|---|---|
| Orchestrator | which tool next, when evidence suffices, when to escalate | compute scores, assert unverified facts, make final decisions |
| Tools | retrieve and measure | interpret |
| Rubric | the score and the band | anything requiring judgement |
| Compliance Writer | prose | numbers |
| Human | the decision | -- |

If domain logic starts appearing in `agent/`, it belongs in a tool. If the model starts
producing numbers, the rubric is not being called.

## AWS mapping

| Concern | Service |
|---|---|
| Agent hosting, session isolation | Bedrock AgentCore Runtime |
| Tools exposed to the agent | AgentCore Gateway (Lambda into MCP tools) |
| Per-supplier assessment history | AgentCore Memory (incremental re-screening) |
| Regulatory knowledge (EUDR text, guidance) | Bedrock Knowledge Bases + S3 |
| **Audit trail** | AgentCore Observability -- every tool call traced |
| Scheduled re-screening | Step Functions + EventBridge |
| Output constraints | Bedrock Guardrails |

The audit trail is the point worth making to judges: for a compliance product, the
regulator-facing requirement (*show your working*) is satisfied by a platform feature,
not by something bolted on afterwards.

## SAP mapping

| Concern | Component |
|---|---|
| Supplier master data, approval workflow | SAP Ariba SLP |
| Secure bridge to the ERP landscape | SAP BTP / BAIP |
| Conversational access for procurement | SAP Joule |

For the hackathon, **mock the Ariba interface**. Show where it plugs in; do not spend a
week on a real integration that is not scored.

## Model routing

Two models, two jobs (`config.py`):

- `MODEL_ORCHESTRATOR` -- branching decisions, final synthesis. Low volume, high judgement.
- `MODEL_EXTRACTION` -- parsing, normalising names, tidying fields. High volume, low judgement.

Bedrock's Converse API keeps the request shape identical across model families, so this
is configuration rather than a rewrite. Worth demonstrating on stage: run the same
screening on two models and show the tool-call traces side by side.

Hackathon credits are finite. This is not premature optimisation.

## Where the agent ends and the pipeline begins

`scripts/run_screening.py` runs the whole dossier assembly with the sequence hardcoded,
including the adjacent-parcel branch. That script is the **reference implementation**:
when the Bedrock loop is wired up, it calls exactly the same functions. If the agent's
output diverges from the script's, the agent is wrong.

Keeping the two separate also means the team can build tools, rubric and DDS output
before any AWS account exists.
