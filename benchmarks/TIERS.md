| task | threads | sync | mechanisms | states | computed | nearest | violations | declared | source |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| atomic-data/atomic_lost_update | 2 | 1 | Atomic | 127 | L1 | L1 |  | L1 | legacy |
| atomic-data/bounded_counter_invariant | 2 | 1 | Mutex | 31 | L1 | L1 |  | L1 | legacy |
| atomic-data/counter_overflow_safety | 2 | 1 | Mutex | 40 | L1 | L1 |  | L1 | legacy |
| channel/bounded_backpressure_lock_held | 2 | 1 | Channel | 20 | L1 | L1 |  | L1 | legacy |
| channel/rendezvous_both_send | 2 | 1 | Channel | 9 | L1 | L1 |  | L1 | legacy |
| channel/send_while_holding_mutex | 2 | 1 | Channel | 9 | L1 | L1 |  | L1 | legacy |
| condvar/bare_wait_no_predicate | 2 | 2 | Condvar | 43 | L1 | L1 |  | L1 | legacy |
| condvar/lost_wakeup_notify_before_wait | 2 | 2 | Condvar | 43 | L1 | L1 |  | L1 | legacy |
| condvar/notify_one_multi_waiter_wrong_pick | 3 | 4 | Condvar,Semaphore | 74 | None | L1 | sync_resources<=2 and mechanisms<=1 | L1 | legacy |
| condvar/two_cv_two_locks | 3 | 5 | Condvar,Semaphore | 109 | None | L1 | sync_resources<=2 and mechanisms<=1 | L1 | legacy |
| lock-order/abba_2lock | 2 | 2 | Mutex | 39 | L1 | L1 |  | L1 | legacy |
| lock-order/cross_module_cycle | 2 | 2 | Mutex | 39 | L1 | L1 |  | L1 | legacy |
| lock-order/cycle_3lock | 3 | 3 | Mutex | 286 | None | L1 | sync_resources<=2 and mechanisms<=1 | L1 | legacy |
| lock-order/partial_deadlock_bystander | 3 | 2 | Mutex | 149 | L1 | L1 |  | L1 | legacy |
| lock-order/two_independent_cycles | 4 | 4 | Mutex | 1371 | L2 | L2 |  | L1 | legacy |
| semaphore/acquire_twice_no_release | 2 | 1 | Semaphore | 35 | L1 | L1 |  | L1 | legacy |
| semaphore/permit_leak | 2 | 1 | Semaphore | 23 | L1 | L1 |  | L1 | legacy |
| semaphore/throttle_n_permits | 3 | 1 | Semaphore | 92 | L1 | L1 |  | L1 | legacy |
| structure/finite_call_loop | 0 | 0 |  | 6 | L1 | L1 |  | L1 | legacy |
| structure/nested_scope_lock_order | 3 | 2 | Mutex | 41 | L1 | L1 |  | L1 | legacy |
| structure/scope_bound_k_workers | 3 | 1 | Semaphore | 116 | L1 | L1 |  | L1 | legacy |
| structure/scope_worker_abba | 2 | 2 | Mutex | 39 | L1 | L1 |  | L1 | legacy |
| structure/spawn_join_loop_finite | 1 | 0 |  | 10 | L1 | L1 |  | L1 | legacy |
| structure/worker_with_payload | 2 | 1 | Mutex | 47 | L1 | L1 |  | L1 | legacy |

## declared counts
- L1: 24

## computed counts
- L1: 20
- L2: 1
- unclassified: 3

## declared != computed
- condvar/notify_one_multi_waiter_wrong_pick: declared L1, computed None
- condvar/two_cv_two_locks: declared L1, computed None
- lock-order/cycle_3lock: declared L1, computed None
- lock-order/two_independent_cycles: declared L1, computed L2

## tier_source nearest
- (none)

## legacy outside BASELINE.json
- condvar/two_cv_two_locks
