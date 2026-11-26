import io
from email.message import EmailMessage

import pytest

from segnaposto.documenti import FOGLIO, esporta, leggi
from segnaposto.motore import Segnaposto
from segnaposto.tabella import Tabella


@pytest.fixture(scope="module")
def sp():
    return Segnaposto()


def _xlsx(fogli):
    from openpyxl import Workbook
    wb = Workbook()
    wb.remove(wb.active)
    for nome, righe in fogli.items():
        ws = wb.create_sheet(nome)
        for r in righe:
            ws.append(r)
    b = io.BytesIO(); wb.save(b); return b.getvalue()


def _docx():
    from docx import Document
    d = Document()
    d.add_paragraph("Offerta per Mario Rossi della Bianchi Srl.")
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text, t.cell(0, 1).text = "Referente", "Telefono"
    t.cell(1, 0).text, t.cell(1, 1).text = "Lucia Ferretti", "347 123 4567"
    d.sections[0].footer.paragraphs[0].text = "Bianchi Srl · Via Roma 12, 36100 Vicenza · P.IVA 01234567897"
    b = io.BytesIO(); d.save(b); return b.getvalue()


def test_excel_colonne_riconosciute_e_ritorno(sp):
    dati = _xlsx({"Clienti": [["Ragione sociale", "Referente", "Email", "Fatturato"],
                              ["Zeta Impianti", "Gino Pilotto", "g.pilotto@zeta.it", 120000],
                              ["Officina Moro", "Ada Sbalchiero", "ada@moro.it", 45000.5]],
                  "Note": [["Nota"], ["Richiamare Gino Pilotto lunedì"]]})
    doc = leggi("clienti.xlsx", dati)
    assert doc.formato == "tabella" and FOGLIO + "Clienti" in doc.testo
    assert any("Referente" in c for c in doc.colonne)
    r = sp.pseudonimizza(doc.testo, Tabella(), forzati=doc.forzati)
    for v in ("Zeta Impianti", "Gino Pilotto", "Sbalchiero", "ada@moro.it"):
        assert v not in r.testo  # anche nel foglio «Note», grazie alla colonna Referente
    assert "120000" in r.testo  # i numeri restano
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(esporta(r.testo, "xlsx")[0]))
    assert wb.sheetnames == ["Clienti", "Note"]
    ws = wb["Clienti"]
    assert ws["A1"].value == "Ragione sociale" and ws["D2"].value == 120000 and ws["B2"].value.startswith("[")


def test_word_con_tabella_e_pie_di_pagina(sp):
    doc = leggi("offerta.docx", _docx())
    assert "Lucia Ferretti\t347 123 4567" in doc.testo and "P.IVA 01234567897" in doc.testo
    r = sp.pseudonimizza(doc.testo, forzati=doc.forzati)
    for v in ("Mario Rossi", "Lucia Ferretti", "347 123 4567", "Via Roma 12", "01234567897"):
        assert v not in r.testo
    from docx import Document
    d = Document(io.BytesIO(esporta(r.testo, "docx")[0]))
    assert len(d.tables) == 1 and d.tables[0].cell(1, 0).text.startswith("[")


def test_csv_italiano():
    doc = leggi("a.csv", "Nome;Cognome;Città\nMario;Rossi;Schio\n".encode("cp1252"))
    assert doc.testo.splitlines()[1] == "Mario\tRossi\tSchio" and doc.forzati["Rossi"] == "PERSONA"
    assert esporta(doc.testo, "csv")[0].decode("utf-8-sig").splitlines()[0] == "Nome;Cognome;Città"


def test_email_con_allegato(sp):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = "Paolo Zanella <p.zanella@esempio.it>", "info@fabrika06.com", "Reclamo ordine"
    m.set_content("Buongiorno,\nil furgone targato AB 123 CD non è arrivato.\nPaolo Zanella")
    m.add_alternative("<p>Buongiorno,<br>il furgone <b>targato AB 123 CD</b> non è arrivato.</p><p>Paolo Zanella</p>", subtype="html")
    m.add_attachment("Nome;Telefono\nPaolo Zanella;3471234567\n".encode(), maintype="text", subtype="csv", filename="contatti.csv")
    m.add_attachment(b"\x89PNG", maintype="image", subtype="png", filename="foto.png")
    doc = leggi("reclamo.eml", bytes(m))
    assert "Oggetto: Reclamo ordine" in doc.testo and "--- Allegato: contatti.csv ---" in doc.testo
    assert any("foto.png" in a for a in doc.avvisi)
    r = sp.pseudonimizza(doc.testo, forzati=doc.forzati)
    for v in ("Zanella", "p.zanella@esempio.it", "AB 123 CD", "3471234567"):
        assert v not in r.testo


def _pdf(righe):
    """Un PDF minimo scritto a mano, con testo vero (Helvetica)."""
    flusso = "BT /F1 12 Tf 50 750 Td " + " ".join(f"({r}) Tj 0 -16 Td" for r in righe) + " ET"
    oggetti = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
               f"<< /Length {len(flusso)} >>\nstream\n{flusso}\nendstream", "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, pos = "%PDF-1.4\n", []
    for i, o in enumerate(oggetti, 1):
        pos.append(len(out)); out += f"{i} 0 obj\n{o}\nendobj\n"
    x = len(out)
    out += f"xref\n0 {len(oggetti) + 1}\n0000000000 65535 f \n" + "".join(f"{q:010d} 00000 n \n" for q in pos)
    out += f"trailer\n<< /Size {len(oggetti) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF\n"
    return out.encode("latin-1")


def test_pdf_con_testo():
    doc = leggi("c.pdf", _pdf(["Contratto con Mario Rossi,", "codice fiscale RSSMRA80A01L840J."]))
    assert "RSSMRA80A01L840J" in doc.testo and doc.formato == "pdf"
    with pytest.raises(ValueError, match="testo leggibile"):
        leggi("s.pdf", _pdf([]))  # pagina bianca: né testo né niente da leggere con l'OCR


def test_formati_non_leggibili():
    with pytest.raises(ValueError, match="docx"):
        leggi("vecchio.doc", b"x")
    with pytest.raises(ValueError, match="non si apre"):
        leggi("foto.jpg", b"x")
    with pytest.raises(ValueError, match="JPG"):
        leggi("foto.heic", b"x")


def test_correzioni_a_mano(sp):
    t = Tabella()
    r = sp.pseudonimizza("Ho parlato con Gianni del magazzino Nord.", t, forzati={"magazzino Nord": "DATO"})
    assert "magazzino Nord" not in r.testo
    r2 = sp.pseudonimizza("Ho parlato con Gianni del magazzino Nord.", t, ignora={"Gianni"})
    assert "Gianni" in r2.testo


def test_indirizzi(sp):
    r = sp.pseudonimizza("Consegna in Corso XX Settembre 45, 36100 Vicenza (VI) entro venerdì; per via di un ritardo.")
    assert "XX Settembre" not in r.testo and "[INDIRIZZO_1]" in r.testo and "per via di" in r.testo


def test_tabella_non_riassegna_numeri():
    t = Tabella()
    t.segnaposto("PERSONA", "A"); t.segnaposto("PERSONA", "B")
    assert t.rimuovi("A") == "[PERSONA_1]"
    assert t.segnaposto("PERSONA", "C") == "[PERSONA_3]"


# ---------------------------------------------------------------- OCR e oscuramento

RIGHE = ["Spett.le Bianchi Srl", "Gentile Ing. Marco Dal Santo,", "la merce consegnata il 3 novembre è arrivata danneggiata.",
         "Il referente è Lucia Ferretti, tel. 347 123 4567,", "IBAN per il rimborso: IT60 X054 2811 1010 0000 0123 456."]


def _immagine(righe=RIGHE, ruota=0.0):
    from PIL import Image, ImageDraw, ImageFont
    font = ImageFont.load_default(size=30)
    im = Image.new("RGB", (1240, 120 + 68 * len(righe)), "white")
    d = ImageDraw.Draw(im)
    for i, r in enumerate(righe):
        d.text((60, 50 + i * 68), r, font=font, fill=(20, 20, 20))
    return im.rotate(ruota, expand=True, fillcolor="white") if ruota else im


def _byte(im, formato):
    b = io.BytesIO(); im.save(b, formato); return b.getvalue()


def test_ocr_foto(sp):
    doc = leggi("reclamo.jpg", _byte(_immagine(ruota=1.5), "JPEG"))
    assert doc.formato == "immagine" and doc.ocr_pagine == 1
    for v in ("Marco Dal Santo", "Lucia Ferrett", "347 123 4567", "IT60 X054"):  # l'OCR può leggere «Ferrettí»
        assert v in doc.testo, doc.testo
    r = sp.pseudonimizza(doc.testo)
    assert "Ferrett" not in r.testo and "[IBAN_1]" in r.testo


def test_pdf_scansionato_e_misto():
    scansione = _byte(_immagine(), "PDF")
    doc = leggi("scansione.pdf", scansione)
    assert doc.ocr_pagine == 1 and "Lucia Ferrett" in doc.testo and any("OCR" in a for a in doc.avvisi)


def test_pdf_oscurato_da_testo_e_da_scansione(sp):
    import pypdfium2 as pdfium
    from segnaposto.oscura import oscura
    for nome, dati in (("contratto.pdf", _pdf(["Contratto con Mario Rossi,", "codice fiscale RSSMRA80A01L840J."])),
                       ("scansione.pdf", _byte(_immagine(), "PDF")), ("foto.png", _byte(_immagine(), "PNG"))):
        doc = leggi(nome, dati)
        t = Tabella()
        sp.pseudonimizza(doc.testo, t)
        valori = {v: s for s, v in t.valori.items()}
        o = oscura(nome, dati, valori)
        assert o.pagine == 1 and o.coperti >= len(valori) and o.non_trovati == [], (nome, o.non_trovati)
        pdf = pdfium.PdfDocument(o.pdf)
        assert pdf[0].get_textpage().get_text_range().strip() == ""  # solo immagini: niente testo da copiare
