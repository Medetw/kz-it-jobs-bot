"""
Telegram bot runner — scheduler, channel posting, DM handlers, admin commands.

Usage:
    python bot.py                  # Normal run (infinite loop with scheduler)
    python bot.py --once           # Single scrape cycle then exit (cron mode)
    python bot.py --mock           # Use mock data, no network calls
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from typing import List, Optional

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    Message,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import config
from classifier import classify
from contact_extractor import extract_contacts
from database import Vacancy, db
from formatter import (
    build_filter_keyboard,
    build_inline_keyboard,
    contacts_from_vacancy,
    format_filter_menu,
    format_stats_message,
    format_vacancy_card,
)
from parsers import HHParser, HabrParser, TelegramChannelParser

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# ── FSM States ────────────────────────────────────────────────────────────────

class FilterState(StatesGroup):
    selecting = State()


# ── Routers ───────────────────────────────────────────────────────────────────

user_router = Router()
admin_router = Router()


# ── User commands ─────────────────────────────────────────────────────────────

@user_router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    """Handle /start command."""
    await state.clear()
    await message.answer(
        "👋 <b>Привет!</b>\n\n"
        "Я помогаю находить IT-вакансии и стажировки в Казахстане 🇰🇿\n\n"
        "📌 <b>Команды:</b>\n"
        "/filter — настроить треки (Backend, Frontend, QA...)\n"
        "/latest — 5 последних вакансий по вашим фильтрам\n"
        "/help — справка\n\n"
        "🚀 Используйте <b>/filter</b> чтобы начать!",
        parse_mode="HTML",
    )


@user_router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "📖 <b>Справка по командам</b>\n\n"
        "/start — приветствие и помощь\n"
        "/filter — выбрать IT-треки и фильтры\n"
        "/latest — получить 5 свежих вакансий\n\n"
        "<i>Вакансии автоматически публикуются в канале каждые "
        f"{config.POLL_INTERVAL_MINUTES} минут.</i>",
        parse_mode="HTML",
    )


@user_router.message(Command("filter"))
async def cmd_filter(message: Message, state: FSMContext) -> None:
    """Show the track filter selection menu."""
    prefs = db.get_subscriber_prefs(message.from_user.id)
    current_tracks = prefs.tracks if prefs else []

    await state.set_state(FilterState.selecting)
    await state.update_data(
        tracks=current_tracks,
        junior_only=prefs.junior_only if prefs else False,
        remote_only=prefs.remote_only if prefs else False,
    )
    await message.answer(
        format_filter_menu(),
        reply_markup=build_filter_keyboard(current_tracks),
        parse_mode="HTML",
    )


@user_router.callback_query(FilterState.selecting, F.data.startswith("filter:"))
async def on_filter_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle filter button presses."""
    action = callback.data.split(":", 1)[1]
    data = await state.get_data()
    tracks: List[str] = data.get("tracks", [])
    junior_only: bool = data.get("junior_only", False)
    remote_only: bool = data.get("remote_only", False)

    if action == "save":
        from database import SubscriberPrefs
        db.set_subscriber_prefs(SubscriberPrefs(
            user_id=callback.from_user.id,
            tracks=tracks,
            junior_only=junior_only,
            remote_only=remote_only,
        ))
        await state.clear()
        await callback.message.edit_text(
            f"✅ <b>Фильтры сохранены!</b>\n\n"
            f"Треки: {', '.join(tracks) if tracks else 'все'}\n"
            f"Только стажировки: {'да' if junior_only else 'нет'}\n"
            f"Только удаленно: {'да' if remote_only else 'нет'}\n\n"
            f"Используйте /latest чтобы получить вакансии.",
            parse_mode="HTML",
        )
        await callback.answer("Сохранено!")
        return

    if action == "junior_only":
        junior_only = not junior_only
        await state.update_data(junior_only=junior_only)
    elif action == "remote_only":
        remote_only = not remote_only
        await state.update_data(remote_only=remote_only)
    elif action in ("backend", "frontend", "qa", "mobile", "data_devops"):
        if action in tracks:
            tracks.remove(action)
        else:
            tracks.append(action)
        await state.update_data(tracks=tracks)

    await callback.message.edit_reply_markup(
        reply_markup=build_filter_keyboard(tracks)
    )
    await callback.answer()


@user_router.message(Command("latest"))
async def cmd_latest(message: Message) -> None:
    """Send 5 most recent matching vacancies to the user in DM."""
    prefs = db.get_subscriber_prefs(message.from_user.id)
    tracks = prefs.tracks if prefs else []
    junior_only = prefs.junior_only if prefs else False
    remote_only = prefs.remote_only if prefs else False

    sent = 0
    if tracks:
        for track in tracks:
            if sent >= 5:
                break
            vacancies = db.get_by_track(
                track=track,
                junior_only=junior_only,
                remote_only=remote_only,
                limit=max(1, 5 - sent),
            )
            for v in vacancies:
                if sent >= 5:
                    break
                await _send_vacancy_to_user(message.chat.id, v, message.bot)
                sent += 1
                await asyncio.sleep(config.POST_DELAY_SECONDS)
    else:
        # No filter set — send latest from all
        vacancies = db.get_by_track(
            track="",
            junior_only=junior_only,
            remote_only=remote_only,
            limit=5,
        )
        for v in vacancies:
            await _send_vacancy_to_user(message.chat.id, v, message.bot)
            sent += 1
            await asyncio.sleep(config.POST_DELAY_SECONDS)

    if sent == 0:
        await message.answer(
            "😔 Вакансий по вашим фильтрам пока нет.\n"
            "Попробуйте расширить фильтры через /filter или подождите следующего обновления.",
            parse_mode="HTML",
        )


# ── Admin commands ────────────────────────────────────────────────────────────

def _is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


@admin_router.message(Command("check_now"))
async def cmd_check_now(message: Message, bot: Bot) -> None:
    """Force an immediate scraping cycle (admin only)."""
    if not _is_admin(message.from_user.id):
        await message.answer("⛔ Только для администраторов.")
        return

    await message.answer("🔄 Запускаю немедленный парсинг...")
    try:
        # Access mock flag from bot context (stored in bot.data)
        mock = getattr(bot, "_mock_mode", False)
        count = await run_scrape_cycle(bot, mock=mock)
        await message.answer(
            f"✅ Готово! Найдено и опубликовано <b>{count}</b> новых вакансий.",
            parse_mode="HTML",
        )
    except Exception as exc:
        logger.exception("check_now error")
        await message.answer(f"❌ Ошибка: {exc}")


@admin_router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    """Show database stats (admin only)."""
    if not _is_admin(message.from_user.id):
        await message.answer("⛔ Только для администраторов.")
        return

    stats = db.stats()
    await message.answer(format_stats_message(stats), parse_mode="HTML")


# ── Core scrape & post pipeline ───────────────────────────────────────────────

async def run_scrape_cycle(bot: Bot, mock: bool = False) -> int:
    """Run a full scraping cycle across all sources and post new vacancies.

    Returns:
        Number of new vacancies posted to the channel.
    """
    logger.info("Starting scrape cycle (mock=%s)", mock)
    all_vacancies: List[Vacancy] = []

    async with HHParser(mock=mock) as hh:
        all_vacancies.extend(await hh.fetch_all())

    async with HabrParser(mock=mock) as habr:
        all_vacancies.extend(await habr.fetch_all())

    async with TelegramChannelParser(mock=mock) as tg:
        all_vacancies.extend(await tg.fetch_all())

    logger.info("Fetched %d total vacancies from all sources", len(all_vacancies))

    posted_count = 0
    for vacancy in all_vacancies:
        # ── Classify ──────────────────────────────────────────────────────────
        classification = classify(
            title=vacancy.title,
            description=vacancy.description,
            location=vacancy.location,
        )

        # Enrich vacancy with classification results
        if classification.track and not vacancy.track:
            vacancy.track = list(config.TRACKS.keys())[
                list(t.name for t in config.TRACKS.values()).index(classification.track.name)
            ] if classification.track else ""
        vacancy.is_junior = classification.is_junior
        vacancy.is_remote = classification.is_remote
        vacancy.hashtags = classification.build_hashtag_string()

        # ── Extract contacts if not already done ──────────────────────────────
        if vacancy.contacts_json in ("{}", ""):
            contacts = extract_contacts(
                f"{vacancy.title}\n{vacancy.description}"
            )
            vacancy.contacts_json = json.dumps({
                "telegram_handles": contacts.telegram_handles,
                "emails": contacts.emails,
                "phones": contacts.phones,
                "recruiter_names": contacts.recruiter_names,
                "linkedin_urls": contacts.linkedin_urls,
            }, ensure_ascii=False)

        # ── Deduplicate & save ────────────────────────────────────────────────
        is_new = db.save_vacancy(vacancy)
        if not is_new:
            continue

        # ── Post to channel ───────────────────────────────────────────────────
        if config.TARGET_CHANNEL:
            await _post_with_retry(bot, vacancy, classification)
            posted_count += 1

    logger.info("Scrape cycle complete: %d new vacancies posted", posted_count)
    return posted_count


async def _post_with_retry(
    bot: Bot,
    vacancy: Vacancy,
    classification,
    max_retries: int = 5,
) -> None:
    """Post a vacancy to the channel with adaptive rate limiting.

    Respects Telegram's RetryAfter flood-control header — if Telegram says
    "wait N seconds", we wait exactly N seconds then retry automatically.
    The POST_DELAY_SECONDS in .env acts as the *minimum* floor between posts.
    """
    from aiogram.exceptions import TelegramRetryAfter, TelegramNetworkError

    for attempt in range(max_retries):
        try:
            await _post_vacancy_to_channel(bot, vacancy, classification)
            db.mark_posted(vacancy.source_id)
            # Minimum floor delay between posts (prevents pre-emptive flooding)
            await asyncio.sleep(config.POST_DELAY_SECONDS)
            return

        except TelegramRetryAfter as e:
            # Telegram told us exactly how long to wait — obey it
            wait = e.retry_after + 1
            logger.warning(
                "Flood control: Telegram says wait %ds before next post (attempt %d/%d)",
                wait, attempt + 1, max_retries,
            )
            await asyncio.sleep(wait)

        except TelegramNetworkError as e:
            wait = 2 ** attempt  # exponential back-off: 1s, 2s, 4s, 8s…
            logger.warning(
                "Network error posting %s: %s — retrying in %ds (attempt %d/%d)",
                vacancy.source_id, e, wait, attempt + 1, max_retries,
            )
            await asyncio.sleep(wait)

        except Exception as exc:
            logger.error("Failed to post %s (no retry): %s", vacancy.source_id, exc)
            return

    logger.error("Gave up posting %s after %d attempts", vacancy.source_id, max_retries)


async def _post_vacancy_to_channel(
    bot: Bot,
    vacancy: Vacancy,
    classification,
) -> None:
    """Format and post a single vacancy card to the configured channel."""
    contacts = contacts_from_vacancy(vacancy)
    text = format_vacancy_card(vacancy, classification, contacts)
    keyboard = build_inline_keyboard(vacancy, contacts)

    await bot.send_message(
        chat_id=config.TARGET_CHANNEL,
        text=text,
        parse_mode="HTML",
        reply_markup=keyboard,
        disable_web_page_preview=True,
    )


async def _send_vacancy_to_user(
    chat_id: int,
    vacancy: Vacancy,
    bot: Bot,
) -> None:
    """Send a vacancy card directly to a user in DM."""
    classification = classify(
        title=vacancy.title,
        description=vacancy.description,
        location=vacancy.location,
    )
    contacts = contacts_from_vacancy(vacancy)
    text = format_vacancy_card(vacancy, classification, contacts)
    keyboard = build_inline_keyboard(vacancy, contacts)

    await bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="HTML",
        reply_markup=keyboard,
        disable_web_page_preview=True,
    )


# ── Entry point ───────────────────────────────────────────────────────────────

async def main(once: bool = False, mock: bool = False) -> None:
    """Initialize bot, dispatcher, scheduler and start polling."""
    if not config.BOT_TOKEN:
        logger.error("BOT_TOKEN is not set. Copy .env.example to .env and fill in values.")
        sys.exit(1)

    # ── Build Bot session (with optional proxy) ───────────────────────────────
    if config.PROXY_URL:
        try:
            from aiohttp_socks import ProxyConnector
            connector = ProxyConnector.from_url(config.PROXY_URL)
            session = AiohttpSession(connector=connector)
            logger.info("Using proxy: %s", config.PROXY_URL)
        except ImportError:
            logger.warning("aiohttp-socks not installed, ignoring PROXY_URL")
            session = AiohttpSession()
    else:
        session = AiohttpSession()

    bot = Bot(token=config.BOT_TOKEN, session=session)
    bot._mock_mode = mock  # type: ignore[attr-defined]

    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    dp.include_router(admin_router)
    dp.include_router(user_router)

    if once:
        # ── Single run mode (for cron jobs) ───────────────────────────────────
        logger.info("Running in --once mode")
        count = await run_scrape_cycle(bot, mock=mock)
        logger.info("--once complete: %d vacancies posted", count)
        await bot.session.close()
        return

    # ── Scheduler mode (infinite loop) ────────────────────────────────────────
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_scrape_cycle,
        trigger="interval",
        minutes=config.POLL_INTERVAL_MINUTES,
        args=[bot, mock],
        id="scrape_cycle",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.start()
    logger.info(
        "Scheduler started — polling every %d minutes",
        config.POLL_INTERVAL_MINUTES,
    )

    # Run initial cycle immediately on startup
    asyncio.create_task(run_scrape_cycle(bot, mock=mock))

    try:
        logger.info("Bot starting polling...")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler.shutdown()
        await bot.session.close()
        logger.info("Bot stopped.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Kazakhstan IT Jobs Telegram Bot")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single scrape cycle and exit (for cron jobs)",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use mock data only, no outbound network calls",
    )
    args = parser.parse_args()

    asyncio.run(main(once=args.once, mock=args.mock))
