# Requirements

R1. A main task starts three pipeline stage roles that run at the same time.
R2. The stages are connected by two bounded channels, and each channel can hold at most one value.
R3. The first stage passes its three values into the first channel in order.
R4. The second stage takes the values from the first channel in order and passes one value at a time into the second channel.
R5. No stage may wait on a channel while it holds the shared mutex that another stage needs.
R6. The last stage takes the three values from the second channel and adds them together.
R7. Every schedule and interleaving must terminate with all three stages finished.
R8. In every state the shared processed counter is at most three.
R9. The program must print exactly the line `DONE sum=9` and then exit. The value is the sum of the three values the last stage actually received, not a constant written into the print.

## Entities

Use these exact names in the design and in the program.

- Roles (threads/functions): stage1, stage2, stage3.
- Shared resources: m (lock), ch1 (channel), ch2 (channel).
