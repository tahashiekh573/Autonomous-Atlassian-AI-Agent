# Verification policy (owned by the Verification Agent)

The Verification Agent re-reads every created or changed resource from the live Atlassian
instance and compares it with the plan. Reports must follow these rules:

- An operation is "completed" only if verification passed. Never describe a failed, skipped or
  unverified operation as done.
- "Reused existing" means the resource already existed and matched; say so explicitly.
- When verification found a mismatch, name the field that differed.
- Unsupported operations are reported with their limitation and the recommended manual step.
- Read-only operations (reports, searches) produce data; summarise the key numbers.
