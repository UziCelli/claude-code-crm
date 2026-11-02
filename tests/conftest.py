import pytest

from app import contas_auto


@pytest.fixture(autouse=True)
def _sem_cache_das_contas_automaticas():
    """O cache por dia das contas automáticas é de processo: cada teste começa sem ele."""
    contas_auto.limpar_cache()
    yield
    contas_auto.limpar_cache()
