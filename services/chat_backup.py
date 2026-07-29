"""
Chat Backup Service - Lưu lịch sử trò chuyện vào Sanity project 10 (backup project).
Mỗi tin nhắn, cuộc trò chuyện đều được backup riêng lẻ, real-time, không đợi periodic backup.
Đảm bảo lịch sử chat không bao giờ mất dù container có bị xóa.

Cách dùng (gọi từ routes_social.py):
  from services.chat_backup import ChatBackup
  ChatBackup.backup_message(msg)
  ChatBackup.backup_conversation(conv, user_ids)
"""
import uuid
import threading
import requests
from datetime import datetime
from services.sanity_service import SanityService, _get_backup_project


class ChatBackup:
    """Backup lịch sử chat vào Sanity project 10 (độc lập, không ảnh hưởng hệ thống)."""

    # Cache để tránh backup trùng lặp conversation liên tục
    _conversation_cache = set()
    _cache_lock = threading.Lock()

    @staticmethod
    def backup_message(message) -> str:
        """
        Backup một tin nhắn vào Sanity project 10 ngay khi được gửi.
        Trả về document ID nếu thành công, None nếu thất bại.
        """
        project = _get_backup_project()
        if not project:
            return None

        doc_id = f"chat-msg-{message.id}"
        doc = {
            "_id": doc_id,
            "_type": "chatMessage",
            "message_id": message.id,
            "conversation_id": message.conversation_id,
            "sender_id": message.sender_id,
            "content": message.content or "",
            "message_type": message.message_type or "text",
            "file_url": getattr(message, 'file_url', '') or "",
            "file_size": message.file_size,
            "created_at": (message.created_at.isoformat() if getattr(message, 'created_at', None) else datetime.utcnow().isoformat()),
            "backup_version": "1.0",
        }

        try:
            url = f"{SanityService._get_base_url(project)}/mutate"
            payload = {"mutations": [{"createOrReplace": doc}]}
            response = requests.post(url, headers=SanityService._get_headers(project), json=payload, timeout=15)
            if response.status_code == 200:
                return doc_id
            return None
        except Exception as e:
            print(f"[ChatBackup] Message backup failed: {e}")
            return None

    @staticmethod
    def backup_messages_batch(messages: list) -> int:
        """
        Backup nhiều tin nhắn cùng lúc (batch).
        Trả về số lượng backup thành công.
        """
        project = _get_backup_project()
        if not project or not messages:
            return 0

        mutations = []
        for msg in messages:
            doc_id = f"chat-msg-{msg.id}"
            doc = {
                "_id": doc_id,
                "_type": "chatMessage",
                "message_id": msg.id,
                "conversation_id": msg.conversation_id,
                "sender_id": msg.sender_id,
                "content": msg.content or "",
                "message_type": msg.message_type or "text",
                "file_url": getattr(msg, 'file_url', '') or "",
                "file_size": msg.file_size,
                "created_at": (msg.created_at.isoformat() if getattr(msg, 'created_at', None) else datetime.utcnow().isoformat()),
                "backup_version": "1.0",
            }
            mutations.append({"createOrReplace": doc})

        try:
            url = f"{SanityService._get_base_url(project)}/mutate"
            payload = {"mutations": mutations}
            response = requests.post(url, headers=SanityService._get_headers(project), json=payload, timeout=30)
            if response.status_code == 200:
                return len(mutations)
            return 0
        except Exception as e:
            print(f"[ChatBackup] Batch backup failed: {e}")
            return 0

    @staticmethod
    def backup_conversation(conversation, member_ids: list = None) -> str:
        """
        Backup một cuộc trò chuyện (khi tạo mới hoặc cập nhật).
        Có cache để tránh backup trùng lặp trong 5 phút.
        """
        # Cache check: tránh backup cùng conversation liên tục
        conv_key = f"{conversation.id}"
        with ChatBackup._cache_lock:
            if conv_key in ChatBackup._conversation_cache:
                return None

        project = _get_backup_project()
        if not project:
            return None

        doc_id = f"chat-conv-{conversation.id}"
        doc = {
            "_id": doc_id,
            "_type": "chatConversation",
            "conversation_id": conversation.id,
            "member_ids": member_ids or [],
            "created_at": (conversation.created_at.isoformat() if getattr(conversation, 'created_at', None) else datetime.utcnow().isoformat()),
            "updated_at": (conversation.updated_at.isoformat() if getattr(conversation, 'updated_at', None) else datetime.utcnow().isoformat()),
            "backup_version": "1.0",
        }

        try:
            url = f"{SanityService._get_base_url(project)}/mutate"
            payload = {"mutations": [{"createOrReplace": doc}]}
            response = requests.post(url, headers=SanityService._get_headers(project), json=payload, timeout=15)
            if response.status_code == 200:
                # Thêm vào cache trong 5 phút
                with ChatBackup._cache_lock:
                    ChatBackup._conversation_cache.add(conv_key)
                # Lên lịch xóa cache sau 5 phút
                threading.Timer(300, ChatBackup._clear_cache, args=[conv_key]).start()
                return doc_id
            return None
        except Exception as e:
            print(f"[ChatBackup] Conversation backup failed: {e}")
            return None

    @staticmethod
    def _clear_cache(key: str):
        """Xóa key khỏi cache."""
        with ChatBackup._cache_lock:
            ChatBackup._conversation_cache.discard(key)

    @staticmethod
    def get_backup_messages(conversation_id: str = None, limit: int = 100) -> list:
        """
        Lấy tin nhắn đã backup từ Sanity project 10.
        Dùng để restore khi database bị xóa.
        """
        project = _get_backup_project()
        if not project:
            return []

        try:
            if conversation_id:
                groq = f'*[_type == "chatMessage" && conversation_id == "{conversation_id}"] | order(created_at asc) [0...{limit}]'
            else:
                groq = f'*[_type == "chatMessage"] | order(created_at desc) [0...{limit}]'
            
            url = f"{SanityService._get_base_url(project)}/query"
            params = {"query": groq}
            response = requests.get(url, headers=SanityService._get_headers(project), params=params, timeout=30)
            if response.status_code == 200:
                result = response.json()
                return result.get("result", [])
            return []
        except Exception as e:
            print(f"[ChatBackup] Failed to fetch backup messages: {e}")
            return []

    @staticmethod
    def get_backup_conversations(user_id: str = None) -> list:
        """
        Lấy danh sách cuộc trò chuyện đã backup từ Sanity project 10.
        """
        project = _get_backup_project()
        if not project:
            return []

        try:
            if user_id:
                groq = f'*[_type == "chatConversation" && "{user_id}" in member_ids] | order(updated_at desc)'
            else:
                groq = '*[_type == "chatConversation"] | order(updated_at desc)'
            
            url = f"{SanityService._get_base_url(project)}/query"
            params = {"query": groq}
            response = requests.get(url, headers=SanityService._get_headers(project), params=params, timeout=30)
            if response.status_code == 200:
                result = response.json()
                return result.get("result", [])
            return []
        except Exception as e:
            print(f"[ChatBackup] Failed to fetch backup conversations: {e}")
            return []