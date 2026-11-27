"""Esporta il riconoscitore di entità italiano in ONNX int8, per usarlo senza PyTorch.

Modello: DeepMount00/Italian_NER_XXL_v2 (Apache 2.0), BERT italiano con oltre 50 categorie di dati.
Uso (serve PyTorch solo qui): python packaging/esporta_modello.py cartella-di-uscita
Lo lancia il workflow «modello» di GitHub Actions, che pubblica i file nella release modello-ner-N.
"""
import hashlib
import json
import sys
from pathlib import Path

import torch
from onnxruntime.quantization import QuantType, quantize_dynamic
from transformers import AutoModelForTokenClassification, AutoTokenizer

REPO = "DeepMount00/Italian_NER_XXL_v2"
REVISIONE = "main"


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "modello-ner")
    out.mkdir(parents=True, exist_ok=True)
    tok = AutoTokenizer.from_pretrained(REPO, revision=REVISIONE)
    m = AutoModelForTokenClassification.from_pretrained(REPO, revision=REVISIONE).eval()
    tok.backend_tokenizer.save(str(out / "tokenizer.json"))
    (out / "etichette.json").write_text(json.dumps({int(k): v for k, v in m.config.id2label.items()}, ensure_ascii=False, indent=1))
    enc = tok("Prova con Mario Rossi a Thiene.", return_tensors="pt")
    nomi = [k for k in ("input_ids", "attention_mask", "token_type_ids") if k in enc]
    assi = {k: {0: "b", 1: "s"} for k in nomi} | {"logits": {0: "b", 1: "s"}}
    grezzo = out / "grezzo.onnx"
    torch.onnx.export(m, tuple(enc[k] for k in nomi), str(grezzo), input_names=nomi, output_names=["logits"],
                      dynamic_axes=assi, opset_version=17, dynamo=False)
    quantize_dynamic(str(grezzo), str(out / "modello.onnx"), weight_type=QuantType.QInt8)
    grezzo.unlink()
    (out / "LEGGIMI.txt").write_text(
        f"Riconoscitore di entità per Riserbo.\nModello originale: https://huggingface.co/{REPO} (licenza Apache 2.0, "
        f"autore DeepMount00).\nConvertito in ONNX e quantizzato int8 per l'esecuzione senza PyTorch.\n", encoding="utf-8")
    hash_ = {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(out.iterdir()) if f.name != "sha256.json"}
    (out / "sha256.json").write_text(json.dumps(hash_, indent=1))
    print(json.dumps({k: round((out / k).stat().st_size / 1e6, 1) for k in hash_}, indent=1))


if __name__ == "__main__":
    main()
