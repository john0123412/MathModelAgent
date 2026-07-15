"""WebSocket 路由模块，提供实时任务消息推送与用户输入接收。"""

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from app.schemas.response import SystemMessage
from app.services import user_input_queue
from app.services.redis_manager import redis_manager
from app.services.ws_manager import ws_manager
from app.utils.common_utils import ensure_safe_task_id
from app.utils.log_util import logger
from app.utils.security import is_valid_websocket_token
from app.config.setting import settings

router = APIRouter()


def _is_websocket_closed(websocket: WebSocket) -> bool:
    return (
        websocket.client_state == WebSocketState.DISCONNECTED
        or websocket.application_state == WebSocketState.DISCONNECTED
    )


def _is_closed_send_error(error: Exception) -> bool:
    text = str(error)
    return (
        "Cannot call \"send\" once a close message has been sent" in text
        or "Unexpected ASGI message 'websocket.send'" in text
    )


def _is_allowed_websocket_origin(origin: str | None) -> bool:
    """Reject cross-site WebSocket connections; CORS middleware does not cover WS."""
    allowed_origins = (
        settings.CORS_ALLOW_ORIGINS
        if isinstance(settings.CORS_ALLOW_ORIGINS, list)
        else [settings.CORS_ALLOW_ORIGINS]
    )
    return origin in allowed_origins


@router.websocket("/task/{task_id}")
async def websocket_endpoint(websocket: WebSocket, task_id: str):
    if not _is_allowed_websocket_origin(websocket.headers.get("origin")):
        logger.warning("拒绝未受信任 Origin 的 WebSocket 连接")
        await websocket.close(code=1008, reason="Untrusted origin")
        return

    # 可选令牌鉴权（与 HTTP 中间件同一开关）：浏览器 WebSocket 无法自定义
    # Authorization 头，改用查询参数 token 携带。前端尚未适配令牌模式，
    # 该开关由部署方 opt-in；默认 None 保持原有行为。
    if settings.API_AUTH_TOKEN and not is_valid_websocket_token(
        websocket.query_params.get("token"), settings.API_AUTH_TOKEN
    ):
        logger.warning("拒绝缺少或无效令牌的 WebSocket 连接")
        await websocket.close(code=1008, reason="Invalid token")
        return

    try:
        safe_task_id = ensure_safe_task_id(task_id)
    except ValueError:
        logger.warning(f"WebSocket task_id 非法: {task_id}")
        await websocket.close(code=1008, reason="Invalid task id")
        return

    logger.info(f"WebSocket 尝试连接 task_id: {safe_task_id}")

    redis_async_client = await redis_manager.get_client()
    if not await redis_async_client.exists(f"task_id:{safe_task_id}"):
        logger.warning(f"Task not found: {safe_task_id}")
        await websocket.close(code=1008, reason="Task not found")
        return
    logger.info(f"WebSocket connected for task: {safe_task_id}")

    # 建立 WebSocket 连接
    await ws_manager.connect(websocket)
    # websocket.timeout 在 Starlette WebSocket 中不可用，已移除
    logger.debug(f"WebSocket connection status: {websocket.client}")

    # 订阅 Redis 频道
    pubsub = await redis_manager.subscribe_to_task(safe_task_id)
    logger.debug(f"Subscribed to Redis channel: task:{safe_task_id}:messages")

    async def _forward_loop():
        while True:
            if _is_websocket_closed(websocket):
                logger.info(f"WebSocket 已关闭，停止转发 task_id: {safe_task_id}")
                break
            try:
                msg = await pubsub.get_message(ignore_subscribe_messages=True)
                if msg:
                    try:
                        msg_dict = json.loads(msg["data"])
                    except Exception as e:
                        logger.error(
                            "Error parsing websocket payload: "
                            f"{type(e).__name__}"
                        )
                        if _is_websocket_closed(websocket):
                            break
                        try:
                            await ws_manager.send_personal_message_json(
                                SystemMessage(
                                    content="实时消息解析失败，已忽略异常数据。",
                                    type="error",
                                ).model_dump(),
                                websocket,
                            )
                        except WebSocketDisconnect:
                            logger.info("WebSocket disconnected while sending parse error notice")
                            break
                        except RuntimeError as send_error:
                            if _is_closed_send_error(send_error):
                                logger.info("WebSocket 已关闭，跳过解析失败提示发送")
                                break
                            raise
                    else:
                        try:
                            await ws_manager.send_personal_message_json(msg_dict, websocket)
                        except WebSocketDisconnect:
                            logger.info("WebSocket disconnected while sending message")
                            break
                        except RuntimeError as send_error:
                            if _is_closed_send_error(send_error):
                                logger.info(
                                    f"WebSocket 已关闭，停止发送后续消息 task_id: {safe_task_id}"
                                )
                                break
                            raise
                await asyncio.sleep(0.1)

            except WebSocketDisconnect:
                logger.info("WebSocket disconnected")
                break
            except Exception as e:
                if _is_closed_send_error(e) or _is_websocket_closed(websocket):
                    logger.info(f"WebSocket 发送通道已关闭，结束循环 task_id: {safe_task_id}")
                    break
                logger.error(f"Error in websocket loop: {type(e).__name__}")
                await asyncio.sleep(1)
                continue

    async def _receive_loop():
        """接收前端发来的实时干预消息，推入按 task_id 隔离的用户输入队列。"""
        while True:
            if _is_websocket_closed(websocket):
                break
            try:
                data = await websocket.receive_json()
            except WebSocketDisconnect:
                logger.info("WebSocket disconnected (receive loop)")
                break
            except Exception as e:
                if _is_websocket_closed(websocket):
                    break
                logger.warning(
                    "WebSocket 接收消息解析失败 "
                    f"task_id={safe_task_id}: {type(e).__name__}"
                )
                continue

            if not isinstance(data, dict):
                continue
            content = data.get("content")
            if data.get("type") == "user_input" and isinstance(content, str) and content.strip():
                if user_input_queue.push(safe_task_id, content):
                    logger.info(f"收到用户实时输入 task_id: {safe_task_id}")
                else:
                    # 队列满（容量上限见 user_input_queue.MAX_QUEUE_SIZE）：
                    # 丢弃并记录，防止未消费消息无限累积占用内存
                    logger.warning(f"用户实时输入队列已满，丢弃消息 task_id: {safe_task_id}")

    try:
        forward_task = asyncio.create_task(_forward_loop())
        receive_task = asyncio.create_task(_receive_loop())
        done, pending = await asyncio.wait(
            {forward_task, receive_task}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        for task in done:
            exc = task.exception()
            if exc:
                logger.error(f"WebSocket 循环异常: {type(exc).__name__}")

    except Exception as e:
        logger.error(f"WebSocket error: {type(e).__name__}")
    finally:
        await pubsub.unsubscribe(f"task:{safe_task_id}:messages")
        ws_manager.disconnect(websocket)
        logger.info(f"WebSocket connection closed for task: {safe_task_id}")
