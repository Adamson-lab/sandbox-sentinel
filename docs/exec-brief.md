# One-page executive brief

**Risk:** Sandboxes are where ungoverned spend, forgotten data and unmanaged access accumulate. Typical failure: a forgotten GPU cluster or leaked key costs six figures over a weekend; the audit finds orphaned data stores in unapproved regions.

**Control:** Every sandbox is born with an expiry, a dollar ceiling and an identity. It cannot be created outside policy, cannot outlive its TTL, and is frozen *before* it exceeds budget. Three independent layers enforce this; every decision is tamper-evident.

**Evidence the board can ask for:** `sentinel verify` (audit integrity) · `demo-report.html` (spend vs. budget with enforcement events) · test suite in CI.

**KPIs:** orphaned sandboxes = 0 · max overshoot as % of budget · mean time to freeze · % sandboxes terminated by TTL vs. manually · denied-request rate by reason.
