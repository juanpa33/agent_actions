import os
import tempfile
from datetime import date
from pathlib import Path

import pytest

# Debe fijarse ANTES de importar hotelsim: config lee HOTELSIM_HOME al importarse.
_TMP = tempfile.mkdtemp(prefix="hotelsim_test_")
os.environ["HOTELSIM_HOME"] = _TMP
os.environ["HOTELSIM_OFFLINE"] = "1"


@pytest.fixture(scope="session")
def world():
    from hotelsim import pipeline
    return pipeline.init(as_of=date(2026, 9, 30), log=lambda *a: None)


@pytest.fixture()
def clean_queue(world):
    from hotelsim import config as C
    if C.QUEUE_FILE.exists():
        C.QUEUE_FILE.unlink()
    yield


@pytest.fixture()
def con(world):   # por test: DuckDB no admite abrir el mismo archivo con configuraciones distintas a la vez
    from hotelsim.gold import connect
    c = connect(read_only=True)
    yield c
    c.close()
