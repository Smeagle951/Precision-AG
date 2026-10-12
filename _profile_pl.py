import time
print("start", flush=True)
from tests.unit.test_precision_lines import sample_project
from plugin.fortsmart_precision.core.precision_lines_engine import run_precision_lines
print("imported", flush=True)
t0 = time.time()
r = run_precision_lines(sample_project())
print("done", round(time.time()-t0, 3), len(r.planting_rows), len(r.shutoff_segments), flush=True)
