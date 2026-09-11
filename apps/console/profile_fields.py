"""Author-facing field descriptions for the governed profile artifacts.

An operator had to author a chunking or retrieval profile as raw JSON, with no way to see
which strategies exist or what the bounds are — the options only lived inside the validator.
These descriptions render a real form *and* the inline help, and they take their choices and
limits from :mod:`apps.artifacts.governed_dsl` so the two cannot disagree.

The client stays non-authoritative: it assembles a body from these fields, and the same
``validate_artifact_body`` still decides whether it is acceptable.
"""

from __future__ import annotations

from typing import Any

from apps.artifacts.governed_dsl import (
    CHUNKING_SIZE_MAX,
    CHUNKING_SIZE_MIN,
    CHUNKING_STRATEGIES,
    MAX_CHUNKS,
    RETRIEVAL_MODES,
    RETRIEVAL_TOP_K_MAX,
    RETRIEVAL_TOP_K_MIN,
)
from apps.artifacts.types import ArtifactType

_CHUNKING_STRATEGY_LABELS = {
    "characters": "Karakter sayısına göre böl",
    "tokens": "Token sayısına göre böl",
    "headings": "Başlıklara göre böl",
    "pages": "Sayfalara göre böl",
    "tables": "Tablolara göre böl",
}

_RETRIEVAL_MODE_LABELS = {
    "keyword": "Anahtar kelime (BM25)",
    "vector": "Anlamsal (vektör)",
    "hybrid": "Hibrit (ikisi birlikte)",
}


def _choice(value: str, label: str) -> dict[str, str]:
    return {"value": value, "label": label}


#: ``kind`` is what the template renders and the client reads: ``select``, ``int`` or
#: ``float``. ``fixed`` fields are the artifact's api_version/kind and are never editable.
PROFILE_FIELDS: dict[str, dict[str, Any]] = {
    ArtifactType.CHUNKING_PROFILE: {
        "label": "Parçalama profili",
        "summary": (
            "Bir dokümanın arama için nasıl parçalara bölüneceğini belirler. Parçalar hem "
            "gömülür hem de cevaba kaynak olarak gösterilir."
        ),
        "fixed": {"api_version": "agenthub/chunking/v1", "kind": "ChunkingProfile"},
        "fields": [
            {
                "name": "strategy",
                "label": "Bölme yöntemi",
                "kind": "select",
                "default": "characters",
                "choices": [
                    _choice(value, _CHUNKING_STRATEGY_LABELS[value])
                    for value in CHUNKING_STRATEGIES
                ],
                "help": (
                    "Karakter/token sabit uzunlukta böler. Başlık, sayfa ve tablo yöntemleri "
                    "dokümanın kendi yapısını izler ve yapılı belgelerde daha isabetlidir."
                ),
            },
            {
                "name": "size",
                "label": "Parça boyutu",
                "kind": "int",
                "default": 1000,
                "min": CHUNKING_SIZE_MIN,
                "max": CHUNKING_SIZE_MAX,
                "help": (
                    "Bir parçanın hedef büyüklüğü. Küçük parçalar daha isabetli eşleşir ama "
                    "bağlamı böler; büyük parçalar bağlamı korur ama gürültü taşır."
                ),
            },
            {
                "name": "overlap",
                "label": "Örtüşme",
                "kind": "int",
                "default": 100,
                "min": 0,
                "max": CHUNKING_SIZE_MAX - 1,
                "help": (
                    "Ardışık parçaların paylaştığı miktar. Sınıra denk gelen bir cümlenin "
                    "ikiye bölünüp kaybolmasını önler. Parça boyutundan küçük olmalıdır."
                ),
            },
            {
                "name": "max_chunks",
                "label": "En fazla parça",
                "kind": "int",
                "default": 1000,
                "min": 1,
                "max": MAX_CHUNKS,
                "help": "Bir dokümandan üretilecek parça sayısının üst sınırı.",
            },
        ],
    },
    ArtifactType.RETRIEVAL_PROFILE: {
        "label": "Arama profili",
        "summary": (
            "Sorgu anında hangi parçaların getirileceğini belirler. Çalışan Retrieve "
            "adımının bağı bu profili kullanır."
        ),
        "fixed": {"api_version": "agenthub/retrieval/v1", "kind": "RetrievalProfile"},
        "fields": [
            {
                "name": "mode",
                "label": "Arama yöntemi",
                "kind": "select",
                "default": "hybrid",
                "choices": [
                    _choice(value, _RETRIEVAL_MODE_LABELS[value]) for value in RETRIEVAL_MODES
                ],
                "help": (
                    "Anahtar kelime birebir terimleri bulur, anlamsal arama yakın anlamlıları "
                    "da getirir. Hibrit ikisini birleştirir ve genelde en dengeli olanıdır."
                ),
            },
            {
                "name": "top_k",
                "label": "Getirilecek parça sayısı",
                "kind": "int",
                "default": 5,
                "min": RETRIEVAL_TOP_K_MIN,
                "max": RETRIEVAL_TOP_K_MAX,
                "help": "Modele bağlam olarak verilecek en iyi parça sayısı.",
            },
            {
                "name": "score_threshold",
                "label": "Alt puan eşiği",
                "kind": "float",
                "default": 0.0,
                "min": 0.0,
                "max": 1.0,
                "step": 0.05,
                "help": (
                    "Bu puanın altındaki parçalar hiç getirilmez. 0 bırakılırsa eşik uygulanmaz."
                ),
            },
            {
                "name": "vector_weight",
                "label": "Anlamsal ağırlık",
                "kind": "float",
                "default": 0.5,
                "min": 0.0,
                "max": 1.0,
                "step": 0.05,
                "only_when": {"mode": "hybrid"},
                "help": "Yalnız hibritte kullanılır. Anahtar kelime ağırlığıyla toplamı 1 olmalı.",
            },
            {
                "name": "keyword_weight",
                "label": "Anahtar kelime ağırlığı",
                "kind": "float",
                "default": 0.5,
                "min": 0.0,
                "max": 1.0,
                "step": 0.05,
                "only_when": {"mode": "hybrid"},
                "help": "Yalnız hibritte kullanılır. Anlamsal ağırlıkla toplamı 1 olmalı.",
            },
        ],
    },
}


def profile_form(artifact_type: str) -> dict[str, Any] | None:
    """Return the author-facing field description for a type, or ``None`` when it has none."""

    return PROFILE_FIELDS.get(artifact_type)


def profile_defaults(artifact_type: str) -> dict[str, Any]:
    """Return the starting body for a new profile of this type.

    A conditional field is included only when its condition already holds for the other
    defaults — and it must be included then, because the validator *requires* the hybrid
    weights and rejects them everywhere else. Dropping every conditional field produced a
    form whose own starting values were invalid.
    """

    schema = PROFILE_FIELDS.get(artifact_type)
    if schema is None:
        return {}
    body: dict[str, Any] = dict(schema["fixed"])
    plain = {
        field["name"]: field["default"] for field in schema["fields"] if not field.get("only_when")
    }
    body.update(plain)
    for field in schema["fields"]:
        condition = field.get("only_when")
        if condition and all(plain.get(key) == value for key, value in condition.items()):
            body[field["name"]] = field["default"]
    return body
