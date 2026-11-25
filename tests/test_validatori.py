from segnaposto.validatori import carattere_controllo_cf, codice_fiscale_valido, iban_valido, partita_iva_valida, targa_valida


def test_codice_fiscale():
    assert codice_fiscale_valido("RSSMRA80A01L840J")
    assert codice_fiscale_valido("rssmra80a01l840j")
    assert not codice_fiscale_valido("RSSMRA80A01L840K")  # carattere di controllo sbagliato
    assert not codice_fiscale_valido("RSSMRA80A01L84")


def test_codice_fiscale_omocodia():
    base = "RSSMRA80A01L84L"  # omocodia: lo 0 finale del comune scritto come L
    assert codice_fiscale_valido(base + carattere_controllo_cf(base))


def test_partita_iva():
    assert partita_iva_valida("01234567897")
    assert partita_iva_valida("IT 01234567897")
    assert not partita_iva_valida("01234567890")
    assert not partita_iva_valida("00000000000")


def test_iban():
    assert iban_valido("IT60X0542811101000000123456")
    assert iban_valido("IT60 X054 2811 1010 0000 0123 456")
    assert not iban_valido("IT61X0542811101000000123456")
    assert not iban_valido("IT60X054281110100000012345")  # lunghezza sbagliata per l'Italia


def test_targa():
    assert targa_valida("AB 123 CD")
    assert targa_valida("ab123cd")
    assert not targa_valida("AI 123 CD")  # la I non si usa nelle targhe
