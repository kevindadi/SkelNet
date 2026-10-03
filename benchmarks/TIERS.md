| task | threads | sync | mechanisms | states | computed | nearest | violations | declared | source |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| buffer/bounded_buffer_2p2c | 4 | 3 | Condvar | 4868 | L2 | L2 |  | L2 | computed |
| buffer/bounded_buffer_semaphores | 4 | 3 | Mutex,Semaphore | 559 | L2 | L2 |  | L2 | computed |
| buffer/sensor_tray | 4 | 3 | Condvar | 4868 | L2 | L2 |  | L2 | computed |
| philosophers/dining_4_waiter | 4 | 5 | Mutex,Semaphore | 7093 | L3 | L3 |  | L3 | computed |
| philosophers/dining_5_ordered | 5 | 5 | Mutex | 13654 | L3 | L3 |  | L3 | computed |
| philosophers/toolbay_5_ordered | 5 | 5 | Mutex | 13654 | L3 | L3 |  | L3 | computed |
| pipeline/three_stage_channels | 3 | 3 | Channel,Mutex | 371 | L2 | L2 |  | L2 | computed |
| printing/print_queue_two_printers | 3 | 3 | Channel,Mutex,Semaphore | 653 | L2 | L2 |  | L2 | computed |
| shutdown/graceful_workers | 3 | 3 | Channel,Mutex,Semaphore | 653 | L2 | L2 |  | L2 | computed |
| transfer/ordered_three_accounts | 3 | 3 | Mutex | 444 | L2 | L2 |  | L2 | computed |
| transfer/ordered_three_warehouses | 3 | 3 | Mutex | 444 | L2 | L2 |  | L2 | computed |

## declared counts
- L2: 8
- L3: 3

## computed counts
- L2: 8
- L3: 3

## declared != computed
- (none)

## tier_source nearest
- (none)

## legacy outside BASELINE.json
- (none)
