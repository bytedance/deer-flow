"""Minimal localization helpers for IM channel user-facing text."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

DEFAULT_LOCALE = "en-US"
PT_BR_LOCALE = "pt-BR"

_TRANSLATIONS: dict[str, dict[str, str]] = {
    "en-US": {
        "artifact.created_file": "Created File: 📎 {filename}",
        "artifact.created_files": "Created Files: 📎 {filenames}",
        "thread.busy": "This conversation is already processing another request. Please wait for it to finish and try again.",
        "session.assistant_id_empty": "Channel session assistant_id is empty. Use 'lead_agent' or a valid custom agent name.",
        "session.assistant_id_invalid": "Invalid channel session assistant_id {raw_value!r}. Use 'lead_agent' or a custom agent name containing only letters, digits, and hyphens.",
        "error.internal": "An internal error occurred. Please try again.",
        "response.none": "(No response from agent)",
        "command.bootstrap_default": "Initialize workspace",
        "command.new.started": "New conversation started.",
        "command.status.active": "Active thread: {thread_id}",
        "command.status.none": "No active conversation.",
        "command.help": (
            "Available commands:\n"
            "/bootstrap - Start a bootstrap session (enables agent setup)\n"
            "/new - Start a new conversation\n"
            "/status - Show current thread info\n"
            "/models - List available models\n"
            "/memory - Show memory status\n"
            "/help - Show this help"
        ),
        "command.unknown": "Unknown command: /{command}. Type /help for available commands.",
        "gateway.fetch_failed": "Failed to fetch {kind} information.",
        "gateway.kind.models": "models",
        "gateway.kind.memory": "memory",
        "gateway.models.available": "Available models:\n{items}",
        "gateway.models.empty": "No models configured.",
        "gateway.memory.status": "Memory contains {count} fact(s).",
        "channel.running": "Working on it...",
        "telegram.welcome": "Welcome to DeerFlow! Send me a message to start a conversation.\nType /help for available commands.",
    },
    "pt-BR": {
        "artifact.created_file": "Arquivo criado: 📎 {filename}",
        "artifact.created_files": "Arquivos criados: 📎 {filenames}",
        "thread.busy": "Esta conversa ja esta processando outra solicitacao. Aguarde a conclusao e tente novamente.",
        "session.assistant_id_empty": "O assistant_id da sessao do canal esta vazio. Use 'lead_agent' ou um nome valido de agente personalizado.",
        "session.assistant_id_invalid": "assistant_id de sessao de canal invalido {raw_value!r}. Use 'lead_agent' ou um nome de agente personalizado com apenas letras, numeros e hifens.",
        "error.internal": "Ocorreu um erro interno. Tente novamente.",
        "response.none": "(Sem resposta do agente)",
        "command.bootstrap_default": "Inicializar workspace",
        "command.new.started": "Nova conversa iniciada.",
        "command.status.active": "Thread ativa: {thread_id}",
        "command.status.none": "Nenhuma conversa ativa.",
        "command.help": (
            "Comandos disponiveis:\n"
            "/bootstrap - Inicia uma sessao de bootstrap (habilita a configuracao do agente)\n"
            "/new - Inicia uma nova conversa\n"
            "/status - Mostra a thread atual\n"
            "/models - Lista os modelos disponiveis\n"
            "/memory - Mostra o estado da memoria\n"
            "/help - Mostra esta ajuda"
        ),
        "command.unknown": "Comando desconhecido: /{command}. Use /help para ver os comandos disponiveis.",
        "gateway.fetch_failed": "Nao foi possivel buscar as informacoes de {kind}.",
        "gateway.kind.models": "modelos",
        "gateway.kind.memory": "memoria",
        "gateway.models.available": "Modelos disponiveis:\n{items}",
        "gateway.models.empty": "Nenhum modelo configurado.",
        "gateway.memory.status": "A memoria contem {count} fato(s).",
        "channel.running": "Trabalhando nisso...",
        "telegram.welcome": "Boas-vindas ao DeerFlow! Envie uma mensagem para iniciar uma conversa.\nUse /help para ver os comandos disponiveis.",
    },
}


def normalize_channel_locale(raw_locale: Any, default_locale: Any = DEFAULT_LOCALE) -> str:
    """Normalize channel locale inputs into a supported locale."""
    for candidate in (raw_locale, default_locale, DEFAULT_LOCALE):
        if not isinstance(candidate, str):
            continue
        normalized = candidate.strip().replace("_", "-").lower()
        if normalized.startswith("pt"):
            return PT_BR_LOCALE
        if normalized.startswith("en"):
            return DEFAULT_LOCALE
    return DEFAULT_LOCALE


def resolve_message_locale(metadata: Mapping[str, Any] | None, default_locale: Any = DEFAULT_LOCALE) -> str:
    """Resolve a locale from inbound metadata."""
    metadata_locale = metadata.get("locale") if isinstance(metadata, Mapping) else None
    return normalize_channel_locale(metadata_locale, default_locale)


def channel_text(locale: Any, key: str, **kwargs: Any) -> str:
    """Return a localized channel string with en-US fallback."""
    resolved_locale = normalize_channel_locale(locale)
    template = _TRANSLATIONS.get(resolved_locale, {}).get(key) or _TRANSLATIONS[DEFAULT_LOCALE][key]
    return template.format(**kwargs)
