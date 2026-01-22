"""
Nudge service for sending inactivity reminders during training.

Monitors user activity and sends nudges at configured intervals.
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional
from aiogram.fsm.context import FSMContext

from bot.core.message_manager import MessageManager
from bot.core.i18n import get_texts
from bot.core.states import TrainingStates

logger = logging.getLogger(__name__)


class NudgeService:
    """Service for managing training inactivity nudges."""
    
    def __init__(self):
        self._active_watchers: dict[str, asyncio.Task] = {}
    
    async def start_training_watcher(
        self,
        chat_id: int,
        user_id: int,
        message_manager: MessageManager,
        state: FSMContext,
        session_id: str,
        lang: str = "en_US"
    ) -> None:
        """Start a nudge watcher for a training session."""
        # Cancel previous watcher if exists
        if session_id in self._active_watchers:
            self._active_watchers[session_id].cancel()
        
        # Start new watcher
        task = asyncio.create_task(
            self._training_nudge_watcher(
                chat_id, user_id, message_manager, state, session_id, lang
            )
        )
        self._active_watchers[session_id] = task
    
    async def stop_watcher(self, session_id: str) -> None:
        """Stop a nudge watcher by session ID."""
        if session_id in self._active_watchers:
            self._active_watchers[session_id].cancel()
            try:
                await self._active_watchers[session_id]
            except asyncio.CancelledError:
                pass
            del self._active_watchers[session_id]
    
    async def _training_nudge_watcher(
        self,
        chat_id: int,
        user_id: int,
        message_manager: MessageManager,
        state: FSMContext,
        session_id: str,
        lang: str
    ) -> None:
        """
        Background watcher that sends inactivity nudges during training.

        Sends up to three nudges:
        - after ~1 minute of inactivity
        - after ~1 hour of inactivity
        - after ~2 days of inactivity
        """
        try:
            thresholds = [60, 3600, 2 * 24 * 3600]  # seconds
            texts = get_texts(lang)

            while True:
                # Stop if state changed or session was reset
                state_name = await state.get_state()
                data = await state.get_data()
                if data.get("nudge_session_id") != session_id:
                    break
                if state_name != TrainingStates.rating_posts:
                    break

                last_ts = data.get("last_activity_ts")
                nudge_stage = int(data.get("nudge_stage", 0) or 0)

                if last_ts is None or nudge_stage >= len(thresholds):
                    await asyncio.sleep(10)
                    continue

                now_ts = datetime.utcnow().timestamp()
                delta = now_ts - float(last_ts)

                if delta >= thresholds[nudge_stage]:
                    # Send nudge
                    nudge_text = texts.get(f"training_nudge_{nudge_stage + 1}", "")
                    if nudge_text:
                        await message_manager.send_ephemeral(
                            chat_id,
                            nudge_text,
                            auto_delete_after=30.0,
                            tag="nudge"
                        )
                    
                    # Increment stage
                    await state.update_data(nudge_stage=nudge_stage + 1)
                
                await asyncio.sleep(10)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error in nudge watcher: {e}")

