import asyncio
import unittest

from app.core.agents.agent import Agent


class AgentCancellationTest(unittest.IsolatedAsyncioTestCase):
    async def test_cancelling_agent_chat_cancels_provider_task(self):
        class HungModel:
            def __init__(self):
                self.cancelled = asyncio.Event()

            async def chat(self, **_kwargs):
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    self.cancelled.set()
                    raise

        cancel_event = asyncio.Event()
        model = HungModel()
        agent = Agent(task_id="task-1", model=model, cancel_event=cancel_event)
        chat_task = asyncio.create_task(agent._chat())
        await asyncio.sleep(0)
        cancel_event.set()

        with self.assertRaises(asyncio.CancelledError):
            await chat_task

        self.assertTrue(model.cancelled.is_set())
