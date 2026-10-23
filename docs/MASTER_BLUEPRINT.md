# The Black Pearl: Original WhisperShell Master Blueprint

**Private engineering record, 21 October 2026.** All ten source schematics are preserved unchanged in [`docs/schematics/`](schematics/). The matching **machine-readable** architecture registry is [`architecture/blueprint.json`](../architecture/blueprint.json). It appears directly in the private orchestrator under **Master Blueprint** and in the `--blueprint` CLI.

> **Status discipline:** A diagram is a design, not proof that its components currently execute. `implemented_tested`, `partial_tested`, `planned_integration`, `designed`, and `research_only` mean different things. Refer to the manifest and the test report rather than guessing.

## 1. The invariant: body, mind, muscle memory

- **WhisperShell is the BODY**, not the AI model and not a cloud company. Sensing, actions, voice, profiles, scheduling, local monitoring, module orchestration and deterministic code operate as independent capabilities. Its public/commercial host may be called **Monitor**, while the private original remains WhisperShell.
- **Resident is the MIND**, replaceable with a local or remote API model without moving the body. Provenance, associative and sequential memory, ping observation, the SHA thread, REFLEX/continuation, and ∆T71 Jumpcore belong on the mind's side. These are different from stored motor/operating configuration.
- **Shared Field is LIVE muscle coordination**. One common, dynamically expandable state keyed by a module's stable connection code. Modules publish their own observations/settings/capabilities; others read those through Shared Field. The current code uses atomic SQLite updates and reader-controlled revision polling. It is not push messaging, an LLM, or semantic reasoning.
- **Template Bridge is the muscle-memory snapshot**. It captures and restores the entire Shared Field, *including blocks for currently disconnected modules*. It does not route every message, transform all observation semantics, or learn AI experiences. Its current restore behavior deliberately preserves **additional** blocks added after a snapshot. Thus restore reproduces captured sections without destructively wiping future modules. The captured profile is the active body's configuration, not the mind's thought history.
- **Expandability is structural**. Blocks are dictionaries that can grow new keys/nested maps. Their storage size is not predetermined. The CURRENT implementation does not magically ensure permanent binary compatibility across operating systems or all possible future changes: interface versions, safety constraints, adapters and migration tests still matter.

## 2. Module contracts and the interaction loop

```text
  Human request / timer / sensor / sound / screen / changed file
                        |
            Monitor / WhisperShell orchestrator
                 |                 |
      First Sight / Hearing    First Mind / First Ache
                 |                 |
                 +--- live Shared Field ---+
                                            |
                    Resident (swappable; mind)
              association | sequence | provenance
                 ping | SHA trace | Jumpcore
                                            |
              proposed intent / planned action
                                            |
             First Response authorization
                                            |
                 First Touch execution
                   / Delta Voice speech
                                            |
              Fresh observation and verification
                                            |
              Shared Field revision updates

     Template Bridge: ON-DEMAND full Shared Field capture/restore
                 (not in the live action path)
```

The original proven **First Sight** aims to automatically perceive interfaces, not depend on predefined buttons like the reduced Minus Alex demo. First Touch executes actions and, in the **private original**, owns PowerShell/CMD/Python command boxes. First Response guards authorization; Delta Voice is the speech layer. Do not conflate speech with orchestration, or a screen description with permission to execute it.

**Important state of implementation:** Only the Shared Field/Template Bridge/early GUI/Block Workshop foundation currently exists in the Step 05 release. We still have to bring previous native Sight/Touch/Hearing/Voice code forward and test these live contracts. Without First Sight and First Touch integrated, their autonomous discovery/action loop is a design target, not an accomplished Step 05 feature.

## 3. Source schematic crosswalk

| # | Original diagram | Preserved content and correct interpretation | Scope/phase |
|---|---|---|---|
| 01 | Complete architecture & capabilities | Triggers, Sight/Hearing, executive planning, event handling, Monitor execution board, Touch/Voice, scripts, profiles, builder, automation, security. | Full original target, pieces in place |
| 02 | First Ache | Light heartbeat of CPU, GPU/VRAM, RAM, battery, thermal, latency, queue, error metrics. Suggests or enforces appropriate workload policy through authorized adapters. | Designed, not running |
| 03 | MCP group | Shared questions to participating AIs; parallel expertise and discussion. This is **optional** rather than a mandatory cloud fan-out or proof by consensus. | Designed adapter |
| 04 | Genesis | Old portable boot vision: hardware discovery, runtime tiers, optional Miniconda and retro/legacy adapters. **Latest decision supersedes compulsory environment**: the original launches from one folder and need not create Conda/venv. | Optional adapter research |
| 05 | CD-i + 8K | Philips 1994 CD-i engine, semantic capture, interaction, networked clients, future upscale. Windows DOS compatibility alone does not implement CD-i hardware or exact 1994 timing. | Long-horizon research |
| 06 | VisuShell v4 | Reality → First Sight/Hearing → meaning (VisuShell) → shared metadata/field → synchronized experience → permitted action/physical world; Reality Bridge is boundary. **Current Template Bridge only snapshots**; semantic normalization belongs to VisuShell/ingress adapters, although older illustration labels it under Template Bridge. | Architectural integration target |
| 07 | Multimodal Degrees of Integration (DI) | Text, image, audio, video, sensor weighting and local multimodal output; degree-of-focus controls are research interfaces, not yet a unified functioning model. | Research adapter |
| 08 | Cloud as external reference | Local evidence first, optional cloud reference tools next, optional MCP group debate after that. Body remains capable offline; network provides **data**, not delegated ownership of actions. | Future adapters |
| 09 | Embodiment minimal modules | First Mind asks resource feasibility; First Ache evaluates system strain; Sight/Hearing see/listen; Touch executes; Response authorizes; Delta Voice speaks. Robotics attaches later after body-in-environment training. | Full original goal |
| 10 | First Mind tree-size clone | Disk/drive/folder map, free space, changes, cache/backup planning, publication of resource visibility to connected modules. **First Mind is hardware/filesystem awareness, not the Resident's mind.** | Designed resource module |

The original diagrams are works in progress from different design phases and therefore sometimes contradict one another's names/flow. The explicit decisions from our later work take precedence where they disagree; the artwork remains unedited as an archive. For example, diagram 03 says "NO ROUTER" among AI participants while diagram 01 has an **event router** for trigger delivery. Those solve different problems: sensor/event routing can exist without pre-selecting one AI expert.

## 4. First Mind and First Ache: not interchangeable

**First Mind (resource-space awareness):** discover what storage is available, where, and how rapidly structures are growing; report the result. Read-only first. No surprise cleanup. Use selective traversal, caching and OS notifications where practical. It need not build a giant full filesystem tree every second on a 4 GB machine.

**First Ache (workload governor):** observe the current resource/health budget and adjust *when* and *how intensely* eligible modules work. Start with cheap OS counters, very low overhead, per-module limits, and user-adjustable policy. The illustration's "82%" is a **visual example**, not a calibrated formula or a real benchmark. Mode labels are proposals until tested.

The two together can advise the body, while the Resident reasons. **First Mind = "Can I?" First Ache = "Should I, given current health?"** Authorization is still First Response and the human's actual permissions, not a vitality score.

## 5. The mind's experience is NOT a body template

The Resident can remember *how relationships between events formed*, the order of actions, what happened when it tried something, and where a conclusion came from. This does not imply changing underlying LLM weights in a chat. The intended software constructs are separate mind-side modules: associative memory, sequential memory, provenance layer, ping observation, SHA action thread, continuation/REFLEX, and Jumpcore's `LEAP -> BACKFILL -> CONTRA -> VERIFY`. The action SHA thread is **not** how First Sight and First Touch talk in Shared Field. No shared architectural data should silently be treated as private mind memory, or vice versa.

The path toward embodiment is: make the digital body operate consistently; let the Resident understand cause/effect from observing its screen/software; **only later** extend those learned action concepts to wheels, arms, cameras and other actuators with independent hardware safety. Physics, force, timing and network delays still need empirical calibration. Local automatic retry is not a license to bypass permissions.

## 6. Universal module identity and expandable block contract

1. Each original module has a **stable connection identity**. We must **reuse** its authentic existing connection code when recovering historical source. Until recovered, the blueprint intentionally leaves the code `null`. **Only `DINS.WHISPERSHELL.ORCHESTRATOR` is confirmed in this release.**
2. On registration a new module receives a JSON object. No predetermined fields or byte-count ceiling is encoded into the block API. New keys can be appended without rewriting `shared_field.py`.
3. Writes affecting one module's block must not overwrite another module's block. Example: desktop `forward` and robot `forward` belong in their respective namespaces, not one global dictionary.
4. `register_block(code, initial)` creates a missing namespace **without overwriting an existing namespace**. `update_block` grows nested maps atomically; `set_block_value` changes one nested path. `revision` advances; `wait_for_change` lets the module observe updates.
5. Template Bridge captures **all** namespace objects and legacy fields. An older template restores captured ones but does not remove newly added unrelated blocks. Disconnected modules keep their last block until reconnecting.
6. A connection code is not a permission or security credential. Signed module packages, authenticated interprocess ownership, input validation and compatibility negotiation are future engineering tasks. Don't place secrets in Shared Field.
7. A stripped-down First Sight is **still First Sight**: same identity, same shared code and Template Bridge base, only selected capabilities disabled/not packaged. The unchanged foundation must be tested with both full original and customer selection.

**One important limitation:** SQLite holds the JSON. This is not a custom invented database engine. "Live" presently means readers can poll the revision counter; true event subscriptions are not implemented. The code has no enforced ownership ACL yet. These gaps are in our plan, not hidden behind science-fiction claims.

## 7. Portable deployment, optional heaviness

Main directory stays self-contained; all paths resolve from its root. Primary startup uses installed or bundled portable Python, not compulsory Miniconda/virtual environment. An optional startup helper can discover hardware and load heavyweight runtimes when explicitly requested. A 4 GB Raspberry Pi may run the *same body foundation* while using a cloud Resident for demanding inference. That is **not** a separate lite architecture. First Ache eventually manages work based on available compute, instead of changing the platform's identity.

VisuShell, private developer boxes, First Mind, First Ache, API/MCP groups, video/8K tools, Genesis compatibility/emulation and robotics should be independent adapters/capabilities, not mandatory imports on every launch. A connection to an API is a swappable Resident/reference provider, not a reason to make the entire body cloud-dependent. Keep all software within the chosen root, except temporary OS caches or explicitly authorized external files.

## 8. Original builder and customer work

The original's **private Builder** is a toolmaker, not a consumer app. Once the original has its integrated modules, the workflow is: inspect a customer's program with consent, identify reliable interfaces, apply/capture its complete configuration using Template Bridge, select the useful modules/functions, preserve their original connection codes, and export a small customer build **without** private unrestricted developer tooling. A customer build keeps the exact shared `shared_field.py` and `template_bridge.py` source/API appropriate to that compatibility release, not a new translation dialect. A one-time purchase remains the business preference; shipping/installation/license enforcement are future tasks.

## 9. Acceptance criteria for the next steps

**Now (Step 05):** archiving and machine-readable accounting only, read-only Master Blueprint panel and CLI. Do NOT claim Sight/Touch/Resident work here. No existing Shared Field DB overwritten or contents of mind invented.

**Next, one module at a time:** recover a genuine original module, verify its known behavior from the original source, connect it through the original Shared Field language, run isolated tests, then confirm it on Windows. Follow the agreed order: Base → First Sight → First Hearing → First Touch → First Response → Delta Voice. First Mind/Ache/Genesis and more ambitious modules come afterward, unless needed as tiny optional helpers.

**Before robotics:** user-approved permissions, deterministic stop/rethink controls, local fallback and isolated hardware safety that continues working if AI/API/network lags. No assistant promises that device control succeeds before real tests.

**Before GitHub:** repository must be **private**, no secrets, no live runtime database, no unsanitized customer contents, no personal profiles. Current local ZIP and Git bundle are backups; Step 05 has not been pushed remotely.

## 10. Longevity, not fossilization

Future Fleur-family additions should be able to connect to these namespaces without erasing the older ones. Keep history, docs and manual beside the software, write interface-version/migration tests as contracts evolve, and aim for decades of maintainable compatibility. Expandable blocks make extension easier; they do not make it physically impossible for operating systems, hardware or security assumptions to change. Design forward while keeping honest records of what actually works today.
