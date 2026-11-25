# Architecture

## 1. Defense in depth — three independent layers

If one layer fails, the next still contains the loss. Layers 2 and 3 do **not** depend on Sentinel's code, database or host.

```mermaid
flowchart TB
    U[Engineer / Data Scientist] -->|request + ticket| G
    subgraph L1["LAYER 1 — Sentinel control plane (fine-grained, 60s loop)"]
        G[Guardrails at the door<br/>TTL cap · budget cap · allow-lists<br/>quota · cost-center cap · worst-case preflight]
        E[Control loop<br/>accrue spend · warn · predict · freeze · kill]
        A[(HMAC-chained audit log)]
        G --> E
        G -.-> A
        E -.-> A
    end
    subgraph L2["LAYER 2 — Cloud-native, independent of our code"]
        B[AWS Budgets Action<br/>at 100% attaches Deny-All to sandbox role]
    end
    subgraph L3["LAYER 3 — Stateless tag reaper (Lambda, 5 min)"]
        R[Terminates anything with expired,<br/>missing or garbled sentinel:expires tag]
    end
    E -->|stop · revoke · terminate| C[(Cloud account<br/>EC2 · RDS · GPU · usage APIs)]
    B -->|deny-all| C
    R -->|terminate| C
    E -->|alerts| N[Slack / Teams / PagerDuty]
```

## 2. Sandbox lifecycle

```mermaid
stateDiagram-v2
    [*] --> ACTIVE: request approved
    [*] --> DENIED: guardrail violation (audited)
    ACTIVE --> ACTIVE: 50% / 80% warn · T-60m / T-10m notice
    ACTIVE --> ACTIVE: extend (four-eyes, capped)
    ACTIVE --> FROZEN: spend ≥ freeze_at<br/>or burn-rate predicts breach
    ACTIVE --> TERMINATED: TTL reached
    ACTIVE --> TERMINATED: spend ≥ kill_at (instant overshoot)
    FROZEN --> TERMINATED: spend ≥ kill_at<br/>or grace period elapsed<br/>or TTL reached
    TERMINATED --> [*]
```

`FROZEN` = compute stopped **and** credentials revoked. A frozen sandbox cannot spend more, but its data survives for `frozen_grace_hours` so work is recoverable by a human with approval.

## 3. Runaway scenario — what happens minute by minute

```mermaid
sequenceDiagram
    autonumber
    participant N as Notebook (runaway loop)
    participant C as Cloud
    participant S as Sentinel loop
    participant O as On-call
    N->>C: $9/min of API + egress charges
    S->>C: refresh resources, drain usage
    S->>S: spend 50% → WARN
    S->>O: Slack: 50% of budget
    S->>S: spend 80% → WARN
    S->>O: Slack: 80% of budget
    S->>S: spend ≥ 100%
    S->>C: stop compute
    S->>C: revoke principal (Deny-All)
    S->>O: PAGE: FROZEN, final spend $X
    N-xC: further calls rejected (403)
    Note over S,C: grace period elapses with no human action
    S->>C: terminate everything
    S->>S: audit: TERMINATED (FROZEN_TIMEOUT)
```

## 4. Decision order inside one tick

```mermaid
flowchart TD
    T[tick] --> AC[refresh + accrue spend]
    AC --> X{TTL reached?}
    X -->|yes| K1[TERMINATE: EXPIRED]
    X -->|no| F{state = FROZEN?}
    F -->|yes| FK{spend ≥ kill_at<br/>or grace over?}
    FK -->|yes| K2[TERMINATE]
    FK -->|no| Z[no-op]
    F -->|no| HK{spend ≥ kill_at?}
    HK -->|yes| K3[TERMINATE: BUDGET_HARD_KILL]
    HK -->|no| FR{spend ≥ freeze_at?}
    FR -->|yes| FZ[FREEZE: BUDGET_EXCEEDED]
    FR -->|no| PR{burn rate breaches<br/>within horizon?}
    PR -->|yes| FZ2[FREEZE: BUDGET_PREDICTED]
    PR -->|no| W{threshold or expiry<br/>notice due?}
    W -->|yes| WN[notify once, audit]
    W -->|no| Z
```
