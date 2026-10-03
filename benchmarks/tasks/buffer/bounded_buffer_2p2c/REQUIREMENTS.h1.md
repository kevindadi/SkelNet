# Requirements

R1. A main task starts two producer roles and two consumer roles that run at the same time.
R2. The producers and the consumers share one bounded buffer that can hold at most one item.
R3. A producer must wait while the buffer is full, and must put its item only when there is room.
R4. A consumer must wait while the buffer is empty, and must take an item only when one is present.
R5. A producer must signal the consumers after it has put an item.
R6. A consumer must signal the producers after it has taken an item.
R7. Every item that is put must eventually be taken, and every schedule must terminate with all four roles finished.
R8. In every state the buffer holds at most one item.
R9. The two items are each taken exactly once.
R10. The program must print exactly the line `DONE sum=3` and then exit. The value is the sum of the two item values that the consumers actually took, not a constant written into the print.

## Entities

Use these exact names in the design and in the program.

- Roles (threads/functions): p1, p2, c1, c2.
- Shared resources: m (lock), not_full (condition variable), not_empty (condition variable).
