# Drop the checkpoints' pages from the page cache (posix_fadvise; no privilege needed), for a cold-disk start.
import os, sys
for p in sys.argv[1:]:
    fd = os.open(p, os.O_RDONLY)
    os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED); os.close(fd); print("evicted", p)
