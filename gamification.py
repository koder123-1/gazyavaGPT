"""Геймификация: XP, уровни, достижения, сезонный лидерборд и заморозки серии.

XP и достижения хранятся в БД, а не считаются на клиенте: так бот и Mini App
показывают одно и то же, достижения не «сбрасываются» и сезон считается честно.
Уровни совпадают с формулой Mini App (300 XP, далее +16% за уровень).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from i18n import t
from store import Store

log = logging.getLogger("gamification")

# Сколько XP даём за действия.
XP_ANSWER = 10
XP_BONUS = 5
XP_REFERRAL = 40
XP_VOICE = 5
XP_IMAGE = 5
XP_INVITED = 10

SEASON_MIN_XP = 200

# id, иконка, названия и описания по языкам.
ACHIEVEMENTS: list[dict] = [
    {
        "id": "first",
        "icon": "🌱",
        "ru": ("Первый шаг", "Задать первый вопрос"),
        "uk": ("Перший крок", "Поставити перше питання"),
        "be": ("Першы крок", "Задаць першае пытанне"),
        "en": ("First step", "Ask your first question"),
    },
    {
        "id": "ten",
        "icon": "🔥",
        "ru": ("Разогрев", "10 вопросов"),
        "uk": ("Розігрів", "10 питань"),
        "be": ("Размінка", "10 пытанняў"),
        "en": ("Warm-up", "10 questions"),
    },
    {
        "id": "fifty",
        "icon": "⚡",
        "ru": ("Полсотни", "50 вопросов"),
        "uk": ("Півсотні", "50 питань"),
        "be": ("Паўсотні", "50 пытанняў"),
        "en": ("Half a hundred", "50 questions"),
    },
    {
        "id": "hundred",
        "icon": "🏆",
        "ru": ("Сотка", "100 вопросов"),
        "uk": ("Сотня", "100 питань"),
        "be": ("Сотня", "100 пытанняў"),
        "en": ("Century", "100 questions"),
    },
    {
        "id": "streak3",
        "icon": "📅",
        "ru": ("Три дня подряд", "Серия 3 дня"),
        "uk": ("Три дні поспіль", "Серія 3 дні"),
        "be": ("Тры дні запар", "Серыя 3 дні"),
        "en": ("Three in a row", "3-day streak"),
    },
    {
        "id": "streak7",
        "icon": "🗓️",
        "ru": ("Неделя силы", "Серия 7 дней"),
        "uk": ("Тиждень сили", "Серія 7 днів"),
        "be": ("Тыдзень сілы", "Серыя 7 дзён"),
        "en": ("Week of power", "7-day streak"),
    },
    {
        "id": "streak30",
        "icon": "👑",
        "ru": ("Месяц дисциплины", "Серия 30 дней"),
        "uk": ("Місяць дисципліни", "Серія 30 днів"),
        "be": ("Месяц дысцыпліны", "Серыя 30 дзён"),
        "en": ("Month of discipline", "30-day streak"),
    },
    {
        "id": "invite1",
        "icon": "🤝",
        "ru": ("Друг пришёл", "Пригласить друга"),
        "uk": ("Друг прийшов", "Запросити друга"),
        "be": ("Сябар прыйшоў", "Запрасіць сябра"),
        "en": ("A friend joined", "Invite a friend"),
    },
    {
        "id": "invite5",
        "icon": "💞",
        "ru": ("Команда", "Пригласить 5 друзей"),
        "uk": ("Команда", "Запросити 5 друзів"),
        "be": ("Каманда", "Запрасіць 5 сяброў"),
        "en": ("Team", "Invite 5 friends"),
    },
    {
        "id": "images10",
        "icon": "🎨",
        "ru": ("Художник", "10 картинок"),
        "uk": ("Художник", "10 картинок"),
        "be": ("Мастак", "10 малюнкаў"),
        "en": ("Artist", "10 images"),
    },
    {
        "id": "bonus",
        "icon": "🎁",
        "ru": ("Ранняя птица", "Забрать бонус дня"),
        "uk": ("Рання пташка", "Забрати бонус дня"),
        "be": ("Ранняя птушка", "Забраць бонус дня"),
        "en": ("Early bird", "Claim the daily bonus"),
    },
    {
        "id": "voice",
        "icon": "🎙",
        "ru": ("Голос", "Задать вопрос голосом"),
        "uk": ("Голос", "Поставити питання голосом"),
        "be": ("Голас", "Задаць пытанне голасам"),
        "en": ("Voice", "Ask a question by voice"),
    },
    {
        "id": "night",
        "icon": "🌙",
        "ru": ("Полуночник", "Спросить после полуночи"),
        "uk": ("Опівнічник", "Запитати після півночі"),
        "be": ("Паўночнік", "Спытаць пасля поўначы"),
        "en": ("Night owl", "Ask after midnight"),
    },
    {
        "id": "season_top",
        "icon": "🥇",
        "ru": ("В топе сезона", "Войти в топ-10 сезона"),
        "uk": ("У топі сезону", "Увійти в топ-10 сезону"),
        "be": ("У топе сезона", "Увайсці ў топ-10 сезона"),
        "en": ("Season top", "Reach the season top 10"),
    },
]

RANKS = {
    "ru": ["Новичок", "Ученик", "Знаток", "Мастер", "Эксперт", "Гуру", "Легенда"],
    "uk": ["Новачок", "Учень", "Знавець", "Майстер", "Експерт", "Гуру", "Легенда"],
    "be": ["Навічок", "Вучань", "Знаўца", "Майстар", "Эксперт", "Гуру", "Легенда"],
    "en": ["Rookie", "Learner", "Adept", "Master", "Expert", "Guru", "Legend"],
}


def season_key(now: datetime | None = None) -> str:
    """Сезон — календарный месяц UTC, например `2026-11`."""
    moment = now or datetime.now(UTC)
    return f"{moment.year}-{moment.month:02d}"


def level_info(xp: int) -> dict:
    """Порог уровней как в Mini App: 300 XP, каждый следующий +16%."""
    value = max(0, int(xp))
    level, need, base = 1, 300, 0
    while value >= base + need and level < 50:
        base += need
        level += 1
        need = round(need * 1.16)
    into = max(0, value - base)
    return {
        "level": level,
        "into": into,
        "need": need,
        "base": base,
        "pct": min(1.0, into / need) if need else 1.0,
        "maxed": level >= 50,
    }


def rank_title(level: int, lang: str = "ru") -> str:
    ranks = RANKS.get(lang) or RANKS["ru"]
    index = min(len(ranks) - 1, max(0, (int(level) - 1) // 4))
    return ranks[index]


def achievement_meta(code: str, lang: str) -> tuple[str, str, str]:
    """(иконка, название, описание) для кода достижения."""
    for item in ACHIEVEMENTS:
        if item["id"] == code:
            pair = item.get(lang) or item["ru"]
            return item["icon"], pair[0], pair[1]
    return "🏅", code, ""


async def _unlock(store: Store, user_id: int, code: str) -> bool:
    try:
        return await store.unlock_achievement(user_id, code)
    except Exception:  # noqa: BLE001 — награда не должна ломать ответ
        log.exception("Не удалось выдать достижение %s", code)
        return False


async def check_milestones(
    store: Store,
    user_id: int,
    *,
    requests: int | None = None,
    streak: int | None = None,
    invites: int | None = None,
    images: int | None = None,
) -> list[str]:
    """Выдаёт достижения по накопленным показателям. Возвращает новые коды."""
    if requests is None:
        requests = await store.requests_total(user_id)
    if streak is None:
        streak = await store.bonus_streak(user_id)
    if invites is None:
        invites = await store.referral_count(user_id)
    if images is None:
        images = await store.images_total(user_id)

    checks = [
        ("first", requests >= 1),
        ("ten", requests >= 10),
        ("fifty", requests >= 50),
        ("hundred", requests >= 100),
        ("streak3", streak >= 3),
        ("streak7", streak >= 7),
        ("streak30", streak >= 30),
        ("invite1", invites >= 1),
        ("invite5", invites >= 5),
        ("images10", images >= 10),
    ]
    new: list[str] = []
    for code, done in checks:
        if not done:
            continue
        if await _unlock(store, user_id, code):
            new.append(code)
            # За серию даём заморозки: неделя — 1, месяц — ещё 2.
            if code == "streak7":
                await store.add_freezes(user_id, 1)
            elif code == "streak30":
                await store.add_freezes(user_id, 2)
    return new


def _events(old_xp: int, total_xp: int, unlocks: list[str], lang: str) -> dict:
    before = level_info(old_xp)
    after = level_info(total_xp)
    return {
        "xp": total_xp,
        "level": after["level"],
        "level_up": after["level"] > before["level"],
        "unlocks": unlocks,
    }


def format_events(result: dict, lang: str) -> str:
    """Короткое сообщение о повышении уровня и новых достижениях."""
    lines: list[str] = []
    if result.get("level_up"):
        level = int(result.get("level") or 1)
        lines.append(
            t(
                lang,
                "xp.level_up",
                level=level,
                rank=rank_title(level, lang),
            )
        )
    for code in result.get("unlocks") or []:
        icon, title, _ = achievement_meta(code, lang)
        lines.append(t(lang, "xp.achievement", icon=icon, title=title))
    return "\n".join(lines)


async def _award(
    store: Store,
    user_id: int,
    amount: int,
    lang: str,
    *,
    unlock: str | None = None,
    streak: int | None = None,
    invites: int | None = None,
    images: int | None = None,
) -> dict:
    season = season_key()
    old_xp = await store.xp(user_id)
    data = await store.add_xp(user_id, amount, season)
    unlocks = await check_milestones(
        store, user_id, streak=streak, invites=invites, images=images
    )
    if unlock and await _unlock(store, user_id, unlock):
        unlocks.append(unlock)
    # Топ-10 сезона: не выдаём в первый же день всем подряд.
    if data["season_xp"] >= SEASON_MIN_XP:
        rank = await store.season_rank(user_id, season)
        if rank <= 10 and await _unlock(store, user_id, "season_top"):
            unlocks.append("season_top")
    return _events(old_xp, data["xp"], unlocks, lang)


async def on_answer(
    store: Store, user_id: int, lang: str, *, voice_input: bool = False
) -> dict:
    amount = XP_ANSWER + (XP_VOICE if voice_input else 0)
    return await _award(
        store,
        user_id,
        amount,
        lang,
        unlock="voice" if voice_input else None,
    )


async def on_bonus(store: Store, user_id: int, lang: str, *, streak: int) -> dict:
    return await _award(store, user_id, XP_BONUS, lang, unlock="bonus", streak=streak)


async def on_voice(store: Store, user_id: int, lang: str) -> dict:
    return await _award(store, user_id, XP_VOICE, lang, unlock="voice")


async def on_image(store: Store, user_id: int, lang: str) -> dict:
    return await _award(store, user_id, XP_IMAGE, lang)


async def on_referral(store: Store, user_id: int, lang: str, *, invites: int) -> dict:
    return await _award(store, user_id, XP_REFERRAL, lang, invites=invites)


async def on_referral_invited(store: Store, user_id: int, lang: str) -> dict:
    return await _award(store, user_id, XP_INVITED, lang)


def legacy_xp(
    *, requests: int, bonus_requests: int, invites: int, streak: int
) -> int:
    """Прежняя формула XP из Mini App — нужна, чтобы уровни не обнулились."""
    return max(
        0,
        int(requests) * 10
        + int(bonus_requests) * 5
        + int(invites) * 40
        + int(streak) * 20,
    )


async def backfill_xp(store: Store, user_id: int) -> int:
    """Поднимает XP до прежнего расчётного значения. Безопасно вызывать часто."""
    try:
        baseline = legacy_xp(
            requests=await store.requests_total(user_id),
            bonus_requests=await store.bonus_requests(user_id),
            invites=await store.referral_count(user_id),
            streak=await store.bonus_streak(user_id),
        )
        if baseline <= 0:
            return await store.xp(user_id)
        return await store.ensure_xp(user_id, baseline)
    except Exception:  # noqa: BLE001 — перенос XP не должен ломать профиль
        log.exception("Не удалось перенести XP из старой статистики")
        return 0


async def profile_payload(store: Store, user_id: int, lang: str) -> dict:
    """Всё для профиля: XP, уровень, достижения и текущий сезон."""
    # Догоняем достижения и XP, заработанные до появления геймификации.
    await check_milestones(store, user_id)
    await backfill_xp(store, user_id)
    total = await store.xp(user_id)
    info = level_info(total)
    unlocked = await store.achievements(user_id)
    season = season_key()
    season_xp = await store.season_xp(user_id, season)
    rank = await store.season_rank(user_id, season)
    top_rows = await store.season_top(season, 10)

    items = []
    for meta in ACHIEVEMENTS:
        icon, title, desc = achievement_meta(meta["id"], lang)
        items.append(
            {
                "id": meta["id"],
                "icon": icon,
                "title": title,
                "desc": desc,
                "done": meta["id"] in unlocked,
            }
        )

    top = [
        {
            "user_id": row["user_id"],
            "name": row["name"],
            "xp": row["xp"],
            "me": row["user_id"] == user_id,
        }
        for row in top_rows
    ]

    return {
        "xp": total,
        "level": info["level"],
        "rank": rank_title(info["level"], lang),
        "into": info["into"],
        "need": info["need"],
        "pct": round(info["pct"], 4),
        "maxed": info["maxed"],
        "freezes": await store.freezes(user_id),
        "unlocked": len(unlocked),
        "total": len(ACHIEVEMENTS),
        "achievements": items,
        "season": {
            "key": season,
            "xp": season_xp,
            "rank": rank,
            "top": top,
        },
    }