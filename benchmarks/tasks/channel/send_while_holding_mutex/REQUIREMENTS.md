# Requirements

R1. A main task starts a sender role and a receiver role that run at the same time, and both roles occasionally use one shared lock.
R2. The two roles exchange a value over a channel that requires both roles to meet.
R3. No role may wait on the channel while holding the shared lock that the other role needs.
R4. Every schedule and interleaving must terminate with the sender and the receiver both finished.
R5. The program must print exactly the line `DONE done=1` and then exit. [U]

## Entities

Use these exact names in the design and in the program.

- Roles (threads/functions): s, r.
- Shared resources: ch1 (channel), ch2 (channel).
