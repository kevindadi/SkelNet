# Spec

A producer and two workers share one work channel that holds at most one task.
The producer puts four tasks into the channel, one at a time, and then signals
shutdown; each worker takes two tasks and exits once shutdown is signalled. A
single shared mutex protects a counter that every role bumps once. The shutdown
signal must reach every worker, so the program terminates under every schedule
with the producer and both workers finished. The program must print the sum of
the task values the workers actually took.
