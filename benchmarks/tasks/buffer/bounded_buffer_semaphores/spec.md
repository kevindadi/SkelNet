# Spec

Two producer roles and two consumer roles share one bounded buffer that holds at
most one item. The buffer is guarded by a mutex, and its free space and its
contents are counted by two semaphores: `slots` starts with one permit and
`items` starts with none. Each producer puts exactly one item and each consumer
takes exactly one item. A producer must take a free slot before it touches the
buffer and signal a new item after it has put one; a consumer must take an item
before it touches the buffer and signal a free slot after it has taken one. The
program must terminate under every schedule and print the sum of the two item
values that the consumers actually took.
