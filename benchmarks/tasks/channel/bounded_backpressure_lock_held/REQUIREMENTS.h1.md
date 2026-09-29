# Requirements

R1. A main task starts a sender role and a receiver role that run at the same time.
R2. The two roles communicate through a channel that can hold at most one value, and both roles occasionally need one shared lock.
R3. The sender passes two values in order and the receiver takes two values, so both roles can finish.
R4. When the channel is full the sender waits before it sends again, and when the channel is empty the receiver waits before it takes.
R5. No role may wait forever for the channel or for the shared lock while the other role still needs to run.
R6. Every schedule and interleaving must terminate with the sender and the receiver both finished.
R7. The sender must not pass its second value before the receiver has taken the first, because the channel holds only one value.
R8. The program must print exactly the line `DONE sender=2 receiver=2` and then exit. Each role keeps, under the shared lock, a count of the values it has handled: the sender counts each of the two values it sends and the receiver counts each of the two values it receives, so each reports 2.

## Entities

Use these exact names in the design and in the program.

- Roles (threads/functions): sender, receiver.
- Shared resources: m (lock), ch (channel).
