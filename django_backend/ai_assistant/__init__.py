"""System-aware read-only AI assistant package.

Modules:
- context: entity/field/relationship metadata (source of truth for planner).
- schemas: Ninja request/response contracts.
- planner: natural-language -> validated query plan (rule-based first, Gemini only for wording/strict-JSON intent assist).
- validators: allowlist enforcement for entities, fields, aggregations, charts.
- permissions: role-aware masking reusing the app's admin convention.
- data_service: ORM-only read-only execution (no raw SQL).
- analytics: aggregations, growth rates, top-N, interpretations from real rows.
- observability: audit logging without sensitive data.
- api: Ninja router exposing POST /chat.
"""
