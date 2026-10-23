> **Historical schematic reconciliation:** see [MASTER_BLUEPRINT.md](MASTER_BLUEPRINT.md) and the [machine-readable master plan](../architecture/blueprint.json). These are the expanded architecture record including First Ache, First Mind, VisuShell, Genesis, DI multimodal, MCP, cloud reference, CD-i and robotics. Source schematics are archived unmodified.

# WhisperShell ORIGINAL: Body and Mind Architecture

## Purpose

A portable Python-based orchestration system intended to run from one folder or removable media. The private full original is a **builder** for future smaller, customer-specific editions. All editions should keep one foundational language and the same Shared Field/Template Bridge files when released together.

## Body: deterministic environment and muscle memory

- **First Sight** (planned integration): observations, screen recognition, markers, coordinates.
- **First Touch** (planned integration): mouse/keyboard/device actions; in the private original, guarded PowerShell/CMD/Python tool interfaces.
- **First Hearing** (planned integration): audio intake.
- **First Response** (planned integration): permission/authority decisions.
- **Delta Voice** (planned integration): speech output.
- **Shared Field** (implemented): independent modules read/write one **live** common state. Expandable blocks preserve owner namespaces.
- **Template Bridge** (implemented): whole-state snapshot/restore of Shared Field, with default/robotics/custom and future named profiles. **It does not synchronize modules during normal operation.**
- **WhisperShell.py** (partially implemented): private top-level orchestration UI, module inventory, model selection, profile capture/apply, script draft workspace, Block Workshop.

The body can operate deterministic functions locally without involving the AI model for every elementary action. The same full core design should work on smaller devices, while capability activation and Resident placement can depend on hardware.

## Mind: experience and reasoning (design, not implemented here)

- **Resident**: swappable local or API-driven AI model.
- **Associative memory**: relationships between concepts, events and experiences.
- **Sequential memory**: order and temporal continuity.
- **Provenance**: where understanding or knowledge came from and how it evolved.
- **Ping/observation layer**: repeated observation of results and surroundings.
- **SHA thread**: trace linking intentions/actions/results, belonging to the **mind** in this design. Not to be confused with Shared Field's SQLite revision counter, or Git commit hashes.
- **Jumpcore (∆T71)**: exploration/verification mechanism with LEAP, BACKFILL, CONTRA, VERIFY.

These are concepts to implement and test **separately from Shared Field and Template Bridge**. A profile snapshot is not an AI memory; a connection code is not a learned association.

## Live interaction concept

```text
    INPUT / OBSERVATION              INTERPRETATION            ACTION
  First Sight / Hearing  --->  Resident / mind  --->  First Touch / Voice
            |                        |                       |
            +------------------------+-----------------------+
                              Shared Field
                   live states, module blocks, revision
                                    |
                             Template Bridge
                       full snapshots on explicit request
```

The diagram is an **intended integration path**, not a claim all pictured components are currently wired.

## Full-original to customer-version workflow

1. Run private ORIGINAL on the customer's software in a controlled test environment, with permission to inspect/integrate.
2. Find actual interface points that First Sight/First Touch and other modules can use.
3. Keep a stable permanent module connection code even if functionality is trimmed.
4. Capture full setup into a Template Bridge profile; sanitize confidential or secret runtime data.
5. Build a customer edition with only needed module features; preserve Shared Field and Template Bridge contract and compatible blocks.
6. Test the reduced build independently, including missing-module behavior and template restoration. **Customer export packager is not built yet.**
7. Keep the full orchestrator, unrestricted development interfaces, research mechanisms and originals private.

Commercial direction discussed: optional one-time licensing rather than mandatory subscription, not implemented in code and not legally documented here.

## Design priorities

Stable module identities; expandable block namespaces; backward compatible module interfaces; isolation between body and mind; paths rooted at the installation folder; avoid unnecessary hard dependencies; hardware-aware activation; ensure actions affecting the physical world have specific, testable safety boundaries when robotics is integrated.
