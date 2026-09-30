# SkelNet experiment protocol (frozen)

> This file is generated from `protocol.json` by `python -m skelnet protocol render`. Do not edit it by hand.

- `protocol.json` sha256: `93eba787905388457c5da83445bd6fbdd35455bf9e18679bbb5ffee2cbfc6e23`
- schema: `skelnet-protocol-v1`
- frozen at commit: `0f3c793`
- frozen at: `2026-09-30T08:07:51Z`

## Models

| display name | model id | channel | thinking | reasoning effort | temperature |
| --- | --- | --- | --- | --- | --- |
| GPT 6 Luna | `gpt-6-luna` | `opencode-go` | yes | medium | provider_default |
| Kimi | `kimi-k2.7-code` | `moonshot-direct` | always | -- | provider_default |
| DeepSeek Flash | `deepseek-flash` | `deepseek-direct` | yes | -- | provider_default |
| Qwen | `qwen3.8-flash` | `dashscope-direct` | yes | -- | provider_default |

## Run parameters

| field | value |
| --- | --- |
| call_budget | 5 |
| hint | h1 |
| max_output_tokens | 32768 |
| max_output_tokens_cap | 65536 |
| seed_policy | per_cell |
| temperature_policy | provider_default |
| token_budget | 200000 |

## Arms and prompt routes

Main groups: G0, SKEL, CIR, REFINE, STATIC, DYNAMIC.

Secondary groups: DYNAMIC_M.

| arm | stage | assets | system sha256 |
| --- | --- | --- | --- |
| CIR | feedback | `concir_generation_v4.md`, `concir_feedback_v1.md` | `2743e2f4e5ae4da07fe74b05e8a97e3f773940d1b2036a77e86d6caeebdcbc7b` |
| CIR | generate | `concir_generation_v4.md` | `6ef31102fc66fa8dab5eef62d8b1a52956822a8f59c6825e360141c1e1fba27b` |
| CIR | rust | `rust_from_cir_v3.md`, `rust_runtime_api_v1.md` | `38034f445193358d7a0f3f7686e8d23104dbd4b2c8e293db06e091f0af52c186` |
| CIR | rust_fix | `rust_compile_fix_v1.md`, `rust_runtime_api_v1.md` | `929a789f506a591150b11b4138af102fa923c5cf5782cf7685f819c2df80afb4` |
| DYNAMIC | generate | `rust_generation_v2.md`, `rust_runtime_api_v1.md` | `346fd7ced59f183cf5237c173153892b1a8fcabc8c0a9ff4dd27f153c1f7149f` |
| DYNAMIC | rust_fix | `rust_compile_fix_v1.md`, `rust_runtime_api_v1.md` | `929a789f506a591150b11b4138af102fa923c5cf5782cf7685f819c2df80afb4` |
| DYNAMIC | tool_feedback | `rust_dynamic_feedback_v1.md`, `rust_runtime_api_v1.md` | `32a953121f8187701afcf7ecd504bb72e946f1728018f5fd1ff50e02e825e8d2` |
| DYNAMIC_M | generate | `rust_generation_v2.md`, `rust_runtime_api_v1.md` | `346fd7ced59f183cf5237c173153892b1a8fcabc8c0a9ff4dd27f153c1f7149f` |
| DYNAMIC_M | rust_fix | `rust_compile_fix_v1.md`, `rust_runtime_api_v1.md` | `929a789f506a591150b11b4138af102fa923c5cf5782cf7685f819c2df80afb4` |
| DYNAMIC_M | tool_feedback | `rust_dynamic_monitor_feedback_v1.md`, `rust_runtime_api_v1.md` | `bbf10295a3c24179a479f6f4fbca1af1eff8041a19a8e3cde2717e93218eb832` |
| G0 | generate | `rust_generation_v2.md`, `rust_runtime_api_v1.md` | `346fd7ced59f183cf5237c173153892b1a8fcabc8c0a9ff4dd27f153c1f7149f` |
| REFINE | generate | `rust_generation_v2.md`, `rust_runtime_api_v1.md` | `346fd7ced59f183cf5237c173153892b1a8fcabc8c0a9ff4dd27f153c1f7149f` |
| REFINE | review | `rust_self_refine_v1.md`, `rust_runtime_api_v1.md` | `b2e2d45a6f273b7e34eda3b05f886e7a5e96bb617aadfe731d2d012724f6bf7f` |
| REFINE | rust_fix | `rust_compile_fix_v1.md`, `rust_runtime_api_v1.md` | `929a789f506a591150b11b4138af102fa923c5cf5782cf7685f819c2df80afb4` |
| SKEL | feedback | `skel_generation_v1.md`, `skel_feedback_v1.md` | `1f9527b333a2c446a45a2e5235a6a1622b9db53e8523e6fee7c9ecb800f69189` |
| SKEL | generate | `skel_generation_v1.md` | `88f784ab8b00b7489553aa6da4d28344713c48b081251ed13bacf84fac1149f0` |
| SKEL | rust | `rust_from_skel_v2.md`, `rust_runtime_api_v1.md` | `8945fdc362a3eb1b180b318ec3be422072969d1500076a9653674f5744c53923` |
| SKEL | rust_fix | `rust_compile_fix_v1.md`, `rust_runtime_api_v1.md` | `929a789f506a591150b11b4138af102fa923c5cf5782cf7685f819c2df80afb4` |
| STATIC | generate | `rust_generation_v2.md`, `rust_runtime_api_v1.md` | `346fd7ced59f183cf5237c173153892b1a8fcabc8c0a9ff4dd27f153c1f7149f` |
| STATIC | rust_fix | `rust_compile_fix_v1.md`, `rust_runtime_api_v1.md` | `929a789f506a591150b11b4138af102fa923c5cf5782cf7685f819c2df80afb4` |
| STATIC | tool_feedback | `rust_static_feedback_v1.md`, `rust_runtime_api_v1.md` | `db8c3acb1fcd4d36be5835ea08d3d8fd49b72468f841c3bb6a7ed175fc4e5b59` |

## Oracle

| field | value |
| --- | --- |
| monitor_runs | 5 |
| oracle_miri_seed_count | 16 |
| oracle_miri_seed_start | 1592594432 |
| oracle_shuttle_seed | 1592590337 |
| pct_max_steps | 10000 |
| random_max_steps | 1000000 |
| shuttle_depth | 3 |
| shuttle_iterations | 2000 |
| stress_runs | 20 |
| stress_timeout | 10.0 |

## Benchmark

`benchmarks/TIERS.md` sha256: `a3d23a4aad082c9649cf467ac1f1b8b37bb9c28a1c1c069973dcadc6ddb04468`

| task | tier | tier source |
| --- | --- | --- |
| atomic-data/atomic_lost_update | L1 | legacy |
| atomic-data/bounded_counter_invariant | L1 | legacy |
| atomic-data/counter_overflow_safety | L1 | legacy |
| boundary/async_select_unsupported | -- | -- |
| boundary/rwlock_unsupported | -- | -- |
| boundary/same_cv_different_locks | -- | -- |
| boundary/unbounded_int_unknown | -- | -- |
| channel/bounded_backpressure_lock_held | L1 | legacy |
| channel/rendezvous_both_send | L1 | legacy |
| channel/send_while_holding_mutex | L1 | legacy |
| condvar/bare_wait_no_predicate | L1 | legacy |
| condvar/lost_wakeup_notify_before_wait | L1 | legacy |
| condvar/notify_one_multi_waiter_wrong_pick | L1 | legacy |
| condvar/two_cv_two_locks | L1 | legacy |
| lock-order/abba_2lock | L1 | legacy |
| lock-order/cross_module_cycle | L1 | legacy |
| lock-order/cycle_3lock | L1 | legacy |
| lock-order/partial_deadlock_bystander | L1 | legacy |
| lock-order/two_independent_cycles | L1 | legacy |
| semaphore/acquire_twice_no_release | L1 | legacy |
| semaphore/permit_leak | L1 | legacy |
| semaphore/throttle_n_permits | L1 | legacy |
| structure/finite_call_loop | L1 | legacy |
| structure/nested_scope_lock_order | L1 | legacy |
| structure/scope_bound_k_workers | L1 | legacy |
| structure/scope_worker_abba | L1 | legacy |
| structure/spawn_join_loop_finite | L1 | legacy |
| structure/worker_with_payload | L1 | legacy |

## Stages

### Stage 0

- tasks: lock-order/abba_2lock, condvar/lost_wakeup_notify_before_wait, atomic-data/atomic_lost_update, lock-order/partial_deadlock_bystander
- groups: G0, SKEL, CIR, REFINE, STATIC, DYNAMIC
- models: gpt-6-luna, kimi-k2.7-code, deepseek-flash, qwen3.8-flash
- reps: 1
- expected paired units: 16
- ledger limits: {"max_requests": 800, "max_tokens": 15000000}
- secondary smoke: DYNAMIC_M x lock-order/abba_2lock x reps=1

### Stage 1

- tasks: (experiment plan)
- groups: G0, SKEL, CIR, REFINE, STATIC, DYNAMIC
- models: gpt-6-luna, kimi-k2.7-code, deepseek-flash, qwen3.8-flash
- reps: 3
- expected paired units: 288
- ledger limits: --
- note: task selection fixed by the experiment plan (coordinator)

### Stage 2

- tasks: (experiment plan)
- groups: G0, SKEL, CIR, REFINE, STATIC, DYNAMIC, DYNAMIC_M
- models: gpt-6-luna, kimi-k2.7-code, deepseek-flash, qwen3.8-flash
- reps: None
- expected paired units: 528
- ledger limits: --
- note: task selection fixed by the experiment plan (coordinator)

### Stage 3

- tasks: (experiment plan)
- groups: G0, SKEL, CIR, REFINE, STATIC, DYNAMIC, DYNAMIC_M
- models: gpt-6-luna, kimi-k2.7-code, deepseek-flash, qwen3.8-flash
- reps: None
- expected paired units: 880
- ledger limits: --
- note: task selection fixed by the experiment plan (coordinator)

## Analysis

- family 1: (SKEL vs G0) (SKEL vs REFINE) (SKEL vs STATIC) (SKEL vs DYNAMIC)
- family 2: (CIR vs G0) (CIR vs REFINE) (CIR vs STATIC) (CIR vs DYNAMIC) (SKEL vs CIR) (SKEL vs DYNAMIC_M)
- multiplicity: holm
- bootstrap: 10000 (seed 20260928)
- alpha: 0.05 (2-sided)
- planned units: 880
- futility margin: 0.03

Success criteria:

- (1) all four main-family Holm p below the O'Brien-Fleming nominal alpha at the current information fraction
- (2) SKEL better than every main baseline in at least 3 of 4 models
- (3) positive SKEL - baseline paired delta on L2 union L3
- (4) the four sensitivity deltas (O1 & O2 & O3) share the main direction
- (5) every main cluster-bootstrap 95% CI lies strictly above zero

## Deviations policy

Any deviation from this frozen protocol after it is frozen must be recorded in experiments/DEVIATIONS.md (file header only at freeze time).
