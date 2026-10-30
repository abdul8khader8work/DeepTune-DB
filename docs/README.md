# DeepTune documentation

Index of the documentation set. `README.md` at the repository root is the entry point; this
directory holds the phase records and the source-of-truth blueprint documents.

## Phase records

| Record | Scope | What it proves |
|---|---|---|
| [`phase-1-ui-skeleton.md`](phase-1-ui-skeleton.md) | `apps/web/` | 3-pane console, design tokens, React Flow DAG, time-travel slider |
| [`phase-2-backend-api.md`](phase-2-backend-api.md) | `apps/api/`, `infra/` | strict contracts, sqlglot guard, EXPLAIN sandbox, hypopg shadow DB |
| [`phase-3-ml-engine.md`](phase-3-ml-engine.md) | `packages/ml-engine/` | EXPLAIN→PyG parser, GATv2 cost model, pruning, beam search |
| [`phase-4-integration.md`](phase-4-integration.md) | web + API + engine | live DAG, copilot streaming, ONNX inference, the DAG morph (§6.1) |

## Blueprints (`blueprints/`)

The original specification documents, kept verbatim as `.docx` / `.pdf` / `.xlsx`. They were
previously scattered across the repository root; Patch 4 centralised them here.

| Document | Covers |
|---|---|
| `GOD_FILE.docx` | the single master brief |
| `MASTER_EXECUTION_PLAN.md.docx` | phase-by-phase execution plan |
| `REVIEWER&Enforcer.docx` | reviewer checklist and the never-list |
| `Create_Reviewer&Enforcer.md.docx` | the prompt that produced the enforcer |
| `System_Architecture_and_Data_Flow.docx` | component topology |
| `Database_Schema_and_Metadata_Model.docx` | metadata tables, target schema |
| `API_Specification_and_Endpoints.docx` | REST contract |
| `ML_Pipeline_and_Model_Training.docx` | graph contract, model, training loop |
| `Evaluation_and_Benchmarking_Strategy.docx` | MAE / RMSE / Spearman ρ, benchmark protocol |
| `Security_and_Deployment_Strategy.docx` | read-only role, secrets, container topology |
| `ui_interface.docx`, `buttons_interface.docx` | layout and design-system specs |
| `Phases of the Project .docx` | milestone breakdown |
| `List_Deliverables.docx`, `List_ProjectSuccess_Metrics.docx`, `List_ProjectTimeline.docx`, `List_Risks&Bottlenecks.docx` | project-management artefacts |
| `User Control Flow AI-Driven Database Query Optimizer & Index Recommender.docx` | user journeys |
| `Research_paper_outline.docx`, `Research_paper_outline.pdf` | paper outline |
| `Literature_Survey_Papers.docx`, `Literature_Survey_Papers.pdf`, `Literature_Survey_Papers_Final.pdf` | literature survey |
| `Literature_Suvery_Papers.xlsx`, `Literature_Suvery_Papers_WITH_Volumnes.xlsx` | survey matrix |
| `patchfile_1.md.docx` | the five-patch remediation brief (patches 0–4) |
| `listing out the essential things.txt` | the original kickoff note |

## Conventions

- Phase records are written as they are verified, not afterwards; each one ends with a reviewer
  checklist and a verification log.
- Code and tests are the executable truth. A record that disagrees with a test is a bug in the
  record.
- Never commit `.env` files, credentials, or model weights (`*.pt`, `*.onnx`,
  `packages/ml-engine/weights/` are git-ignored).
