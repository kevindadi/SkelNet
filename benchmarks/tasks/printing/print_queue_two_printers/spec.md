# Spec

A spooler and two printers share one print queue that holds at most one job.
The spooler queues four print jobs, one at a time, and then signals shutdown;
each printer takes two jobs and exits once shutdown is signalled. A single
shared mutex protects a counter that every role bumps once. The shutdown signal
must reach every printer, so the program terminates under every schedule with
the spooler and both printers finished. The program must print the sum of the
job sizes the printers actually took.
