import pytest


@pytest.fixture(scope="session")
def sp():
    """Il motore con le impostazioni di base (i file di test possono ridefinirlo con anagrafiche e codici propri)."""
    from riserbo.motore import Segnaposto
    return Segnaposto()
