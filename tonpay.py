"""Оплата токеном GRAM (jetton в сети TON) через TON Connect.

Схема без хранения состояния на сервере: пользователь выбирает пакет, сервер
подписывает «намерение» (кто платит, сколько запросов, сколько GRAM, до какого
времени) коротким HMAC-токеном. Клиент открывает TON Connect, кошелёк отправляет
jetton-перевод с этим токеном в комментарии. Проверка оплаты — запрос к TonAPI:
ищем входящий перевод нужного jetton с нашим комментарием и суммой не меньше
ожидаемой. Повторно начислить нельзя: платёж пишется по event_id транзакции.

Зачем jetton-кошелёк получателя, а не сам адрес: в TON токены лежат не на адресе
владельца, а на отдельном контракте jetton-wallet. Перевод делается именно на
него; его адрес для нашего кошелька отдаёт TonAPI (кэшируется на 10 минут).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
from decimal import ROUND_CEILING, Decimal
from typing import Any
from urllib.parse import quote

import aiohttp
from tonsdk.boc import begin_cell
from tonsdk.utils import Address

from config import Settings

log = logging.getLogger("tonpay")

# op-code стандартного jetton-перевода (TEP-74)
JETTON_TRANSFER_OP = 0x0F8A7EA5
# TON на газ для jetton-перевода: 0.05 хватает на forward-комментарий.
FORWARD_TON_NANO = 50_000_000
# Сколько живёт подпись намерения и сколько после этого ещё принимаем оплату.
INTENT_TTL = 1800
CLAIM_WINDOW = 24 * 3600
MAX_REQUESTS = 1_000_000
MIN_GRAMS = Decimal("0.01")
MAX_GRAMS = Decimal("10000")

_JETTON_CACHE: dict[str, tuple[float, str]] = {}


class TonApiError(RuntimeError):
    """TonAPI недоступен или не отдал нужные данные."""


# --------------------------------------------------------------------------- адреса
def raw_address(value: str) -> str:
    """Приводит любой адрес TON к виду «0:hex» для сравнения."""
    raw = (value or "").strip()
    if not raw:
        return ""
    try:
        return Address(raw).to_string(is_user_friendly=False).lower()
    except Exception:  # noqa: BLE001 — уже raw или мусор: сравниваем как есть
        return raw.lower()


def grams_to_nano(grams: Decimal, decimals: int = 9) -> int:
    scale = Decimal(10) ** max(0, int(decimals))
    return int((grams * scale).to_integral_value(rounding=ROUND_CEILING))


# --------------------------------------------------------------------------- цены
def package_price(settings: Settings, requests: int) -> Decimal | None:
    for rq, grams in settings.gram_packages:
        if int(rq) == requests:
            return Decimal(grams)
    return None


def price_for(settings: Settings, requests: int) -> Decimal:
    """Цена в GRAM: набор из настроек либо курс «запросов за 1 GRAM»."""
    fixed = package_price(settings, requests)
    if fixed is not None:
        return fixed
    rate = max(1, int(settings.gram_rate))
    value = Decimal(requests) / Decimal(rate)
    return value.quantize(Decimal("0.01"), rounding=ROUND_CEILING)


def parse_offer(
    settings: Settings, requests: Any = None, grams: Any = None
) -> tuple[int, Decimal] | None:
    """Возвращает (запросы, цена в GRAM) или None, если запрос некорректный."""
    if requests is not None:
        try:
            count = int(requests)
        except (TypeError, ValueError):
            return None
        if not 0 < count <= MAX_REQUESTS:
            return None
        return count, price_for(settings, count)

    if grams is not None:
        try:
            amount = Decimal(str(grams)).quantize(Decimal("0.01"))
        except Exception:  # noqa: BLE001 — «abc» и NaN равносильны ошибке
            return None
        if not MIN_GRAMS <= amount <= MAX_GRAMS:
            return None
        count = int(amount * max(1, int(settings.gram_rate)))
        if count <= 0:
            return None
        return count, amount
    return None


# --------------------------------------------------------------------------- намерение
def _secret(bot_token: str) -> bytes:
    return hmac.new(bot_token.encode("utf-8"), b"gram-intents", hashlib.sha256).digest()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    pad = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + pad)


def sign_intent(bot_token: str, payload: dict[str, Any]) -> str:
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    sig = hmac.new(_secret(bot_token), body.encode("ascii"), hashlib.sha256).digest()
    return f"{body}.{_b64(sig)}"


def verify_intent(
    bot_token: str, token: str, user_id: int, max_age: int = CLAIM_WINDOW
) -> dict[str, Any] | None:
    try:
        body, sig = str(token or "").split(".", 1)
    except ValueError:
        return None
    expect = _b64(hmac.new(_secret(bot_token), body.encode("ascii"), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expect):
        return None
    try:
        payload = json.loads(_unb64(body))
    except Exception:  # noqa: BLE001 — битый base64/JSON
        return None
    if not isinstance(payload, dict) or int(payload.get("u") or 0) != int(user_id):
        return None
    issued = int(payload.get("iat") or 0)
    if issued <= 0 or time.time() - issued > max_age:
        return None
    if not payload.get("m") or not int(payload.get("r") or 0) > 0:
        return None
    return payload


def build_transfer_payload(
    amount_nano: int, destination: str, response_to: str, memo: str
) -> str:
    """Собирает base64-BOC тела jetton-перевода с текстовым комментарием."""
    dest = Address(destination)
    resp = Address(response_to)
    body = (
        begin_cell()
        .store_uint(JETTON_TRANSFER_OP, 32)
        .store_uint(0, 64)  # query_id
        .store_coins(int(amount_nano))
        .store_address(dest)
        .store_address(resp)
        .store_uint(0, 1)  # custom_payload: нет
        .store_coins(1)  # forward_ton_amount: 1 нанотон, чтобы шёл комментарий
        .store_uint(1, 1)  # forward_payload лежит отдельной ячейкой
        .store_ref(begin_cell().store_uint(0, 32).store_bytes(memo.encode("utf-8")).end_cell())
        .end_cell()
    )
    return base64.b64encode(body.to_boc()).decode("ascii")


# --------------------------------------------------------------------------- TonAPI
def _headers(settings: Settings) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if settings.tonapi_key:
        headers["Authorization"] = f"Bearer {settings.tonapi_key}"
    return headers


async def _get_json(session: aiohttp.ClientSession, settings: Settings, path: str) -> dict:
    url = settings.tonapi_base.rstrip("/") + path
    try:
        async with session.get(url, headers=_headers(settings), timeout=aiohttp.ClientTimeout(total=12)) as resp:
            if resp.status != 200:
                text = (await resp.text())[:200]
                raise TonApiError(f"tonapi {resp.status}: {text}")
            data = await resp.json(content_type=None)
    except aiohttp.ClientError as exc:
        raise TonApiError(f"tonapi network: {exc}") from exc
    if not isinstance(data, dict):
        raise TonApiError("tonapi: unexpected response")
    return data


async def jetton_wallet_address(
    session: aiohttp.ClientSession, settings: Settings, *, refresh: bool = False
) -> str:
    """Адрес jetton-кошелька нашего получателя (куда слать GRAM)."""
    owner = raw_address(settings.gram_wallet)
    jetton = raw_address(settings.gram_jetton)
    if not owner or not jetton:
        raise TonApiError("gram wallet is not configured")
    key = f"{owner}:{jetton}"
    cached = _JETTON_CACHE.get(key)
    if cached and not refresh and time.time() - cached[0] < 600:
        return cached[1]
    data = await _get_json(
        session,
        settings,
        f"/v2/accounts/{quote(owner, safe=':')}/jettons/{quote(jetton, safe=':')}",
    )
    address = str((data.get("wallet_address") or {}).get("address") or "")
    if not address:
        raise TonApiError("jetton wallet is not initialized")
    _JETTON_CACHE[key] = (time.time(), address)
    return address


async def find_incoming_transfer(
    session: aiohttp.ClientSession,
    settings: Settings,
    *,
    memo: str,
    expected_nano: int,
    since: int,
) -> dict[str, Any] | None:
    """Ищет входящий GRAM-перевод с нашим комментарием на кошелёк получателя."""
    owner = raw_address(settings.gram_wallet)
    jetton = raw_address(settings.gram_jetton)
    data = await _get_json(
        session, settings, f"/v2/accounts/{quote(owner, safe=':')}/events?limit=100"
    )
    for event in data.get("events") or []:
        if not isinstance(event, dict):
            continue
        try:
            timestamp = int(event.get("timestamp") or 0)
        except (TypeError, ValueError):
            timestamp = 0
        if timestamp and timestamp < since - 120:
            continue
        for action in event.get("actions") or []:
            if not isinstance(action, dict):
                continue
            if (action.get("type") or "") != "jetton_transfer":
                continue
            if (action.get("status") or "ok") != "ok":
                continue
            transfer = action.get("JettonTransfer") or action.get("jetton_transfer") or {}
            if not isinstance(transfer, dict):
                continue
            jetton_addr = raw_address((transfer.get("jetton") or {}).get("address") or "")
            if jetton_addr and jetton_addr != jetton:
                continue
            if (transfer.get("comment") or "") != memo:
                continue
            try:
                amount = int(transfer.get("amount") or 0)
            except (TypeError, ValueError):
                continue
            if amount < expected_nano:
                continue
            event_id = str(event.get("event_id") or event.get("lt") or "")
            if not event_id:
                continue
            return {
                "event_id": event_id,
                "amount": amount,
                "timestamp": timestamp,
                "sender": raw_address((transfer.get("sender") or {}).get("address") or ""),
            }
    return None


async def create_intent(
    session: aiohttp.ClientSession,
    settings: Settings,
    *,
    user_id: int,
    requests: int,
    grams: Decimal,
) -> dict[str, Any]:
    """Готовит платёж: memo, TON Connect-сообщение и подписанный токен."""
    destination_wallet = await jetton_wallet_address(session, settings)
    nonce = base64.urlsafe_b64encode(hashlib.sha256(f"{user_id}:{time.time()}".encode()).digest()[:6]).decode()
    memo = f"gz-{user_id}-{nonce}"
    issued = int(time.time())
    valid_until = issued + INTENT_TTL
    amount_nano = grams_to_nano(grams, settings.gram_decimals)
    payload_b64 = build_transfer_payload(
        amount_nano,
        destination_wallet,
        raw_address(settings.gram_wallet),
        memo,
    )
    token = sign_intent(
        settings.bot_token,
        {
            "u": int(user_id),
            "r": int(requests),
            "g": str(grams),
            "n": amount_nano,
            "m": memo,
            "iat": issued,
        },
    )
    return {
        "token": token,
        "requests": int(requests),
        "grams": f"{grams:.2f}",
        "amount_nano": str(amount_nano),
        "memo": memo,
        "valid_until": valid_until,
        "messages": [
            {
                "address": destination_wallet,
                "amount": str(FORWARD_TON_NANO),
                "payload": payload_b64,
            }
        ],
    }