# Spec

Three warehouses each hold one crate and each has its own dock lock. Three
shipping roles run at the same time: the first ships one crate from the first
warehouse to the second, the second ships one crate from the second warehouse
to the third, and the third ships one crate from the third warehouse back to
the first. Each role must hold the source and destination dock locks at the
same time while it ships its crate, and a warehouse's stock may not be touched
without its lock. The total number of crates across the three warehouses must
stay at three, no warehouse may go negative, and every schedule must terminate
with all three roles finished. The program prints the sum of the three final
stock counts.
