"""Single center Master control-plane reconciler; job scheduling belongs to Kuscia."""
import time
import logging
from app.core.config import settings
from app.services.master_execution import reconcile_once

def main():
    if settings.pets_scheduler_mode != 'master-lite':
        raise SystemExit('master worker requires PETS_SCHEDULER_MODE=master-lite')
    while True:
        try:
            reconcile_once()
        except Exception:
            logging.getLogger(__name__).error('Master reconciliation scan failed')
        time.sleep(max(1, settings.execution_status_poll_seconds))

if __name__ == '__main__':
    main()
