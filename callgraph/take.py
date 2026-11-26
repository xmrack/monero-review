# Copy a pull request head's results out of the directory its build could write:
# regular files only, never through a symlink, size-capped.
# usage: take.py <out dir> <dest dir>
import os, stat, sys

CAP = {"callgraph.json": 30 << 20, "gate.log": 1 << 20}
src, dest = sys.argv[1], sys.argv[2]
os.makedirs(dest, exist_ok=True)
for name, cap in CAP.items():
    try:
        fd = os.open(os.path.join(src, name), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        continue
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode) or st.st_size > cap:
        os.close(fd)
        print(f"take.py: {name} refused")
        continue
    with os.fdopen(fd, "rb") as f:
        data = f.read(cap + 1)
    if len(data) <= cap:
        with open(os.path.join(dest, name), "xb") as out:
            out.write(data)
