# Spec

Two waiter roles each guard their own state with their own lock and wait on a
condition variable bound to that lock; a single notifier announces that both
waiters are ready and then wakes each one on its own condition variable while
holding the corresponding lock.
