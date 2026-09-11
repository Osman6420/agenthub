"""Presentation labels only; stored states and authorization remain unchanged."""

from django import template

register = template.Library()


@register.filter
def document_label(value: str) -> str:
    return {
        "active": "Etkin",
        "quarantined": "Karantinada",
        "archived": "Arşivlendi",
        "disabled": "Devre dışı",
        "draft": "Taslak",
        "building": "Hazırlanıyor",
        "promotable": "Kullanıma alınmaya hazır",
        "superseded": "Önceki sürüm",
        "failed": "Başarısız",
        "pending": "İşlenmeyi bekliyor",
        "parsed": "İşlendi",
        "generic_rest": "REST",
        "confluence_dc": "Confluence",
        "mcp_resource": "MCP",
        "document_set_manager": "Doküman seti yöneticisi",
        "document_set_metadata_viewer": "Set bilgilerini görüntüleyen",
        "document_set_content_reader": "Doküman okuyucusu",
    }.get(value, "Durum doğrulanmalı")


@register.filter
def set_version_label(value: str) -> str:
    return "Hazırlamaya hazır" if value == "promotable" else document_label(value)
