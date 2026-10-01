# Spec

Two producer roles and two consumer roles share one bounded buffer that holds at
most one item. Each producer puts exactly one item; each consumer takes exactly
one item. Producers must block while the buffer is full and consumers must block
while it is empty, and each side must signal the other after it changes the
buffer. The program must terminate under every schedule and print the sum of the
two item values that the consumers actually took.
