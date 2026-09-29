# Requirements

R1. A main task starts a sender role and a receiver role that run at the same time.
R2. The two roles exchange a value over a channel that requires both roles to meet.
R3. No role may wait forever for the other role.
R4. Every schedule and interleaving must terminate with the sender and the receiver both finished.
R5. The program must print exactly the line `DONE done=2` and then exit. Each role adds one to a shared completion counter after it has taken part in the exchange, so the printed count is 2.

## Entities

Use these exact names in the design and in the program.

- Roles (threads/functions): s, r.
- Shared resources: ch1 (channel), ch2 (channel).
