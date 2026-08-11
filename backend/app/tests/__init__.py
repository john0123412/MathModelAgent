"""Test package defaults that prevent lifecycle side effects on live tasks."""

import os


# TestClient starts the real FastAPI lifespan.  The development test process
# must never mark an actively running Docker task as interrupted merely because
# it shares backend/project/work_dir with the service.
os.environ["RECOVER_STALE_TASKS_ON_STARTUP"] = "false"
