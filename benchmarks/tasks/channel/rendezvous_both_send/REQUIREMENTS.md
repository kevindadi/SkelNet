# Requirements

R1. A main task starts one sending task and one receiving task that run at the same time.
R2. The two tasks communicate over a channel with no buffering, so a send and a take must meet to exchange the value.
R3. The sender passes one value and the receiver takes one value, so both tasks finish.
R4. No task may wait forever for a partner that never arrives.
R5. Every schedule and interleaving must terminate with both tasks finished and no value left in the channel.
R6. The channel is empty once both tasks have finished.
R7. The program must print exactly the line `DONE done=1` and then exit. [U]

## Entities

Use these exact names in the design and in the program.

- Roles (threads/functions): s1, r.
- Shared resources: ch (channel).
