"""
Configurazione del logging.

Punto aperto #4: filtro per escludere dai log le chiamate agli
endpoint di health check, controllabile via variabile d'ambiente
LOG_HEALTH_CHECKS (default: False = non loggati).
"""

import logging
import os


class HealthCheckFilter(logging.Filter):
    """Filtra le righe di log relative agli health check."""

    HEALTH_PATHS = {"/health", "/health/db"}

    def filter(self, record: logging.LogRecord) -> bool:
        log_health = os.getenv("LOG_HEALTH_CHECKS", "false").lower() == "true"
        if log_health:
            return True
        message = record.getMessage()
        return not any(path in message for path in self.HEALTH_PATHS)


def setup_logging() -> None:
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()

    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    # Applica il filtro al root logger e a uvicorn.access
    health_filter = HealthCheckFilter()
    logging.getLogger().addFilter(health_filter)

    uvicorn_access = logging.getLogger("uvicorn.access")
    uvicorn_access.addFilter(health_filter)
