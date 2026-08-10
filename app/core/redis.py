"""Redis 客户端（缓存/会话/连接器心跳/异步）。"""
import redis

from app.core.config import settings

redis_client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
