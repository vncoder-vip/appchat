"""
Database Backup Service - Tự động backup/restore toàn bộ database lên Sanity.
Giúp dữ liệu sống sót qua các lần redeploy (khi container bị xóa sạch).
- Backup: dùng Sanity project 10 (backup project)
- Restore: dùng Sanity project 10 (backup project)
"""
import uuid
import threading
import requests
from datetime import datetime
from services.sanity_service import SanityService, _get_backup_project


FULL_BACKUP_DOC_ID = "database-full-backup"


class DatabaseBackupService:
    """Backup & restore toàn bộ database lên Sanity (dùng project 10)."""

    @staticmethod
    def is_db_empty() -> bool:
        """Kiểm tra database có dữ liệu không."""
        try:
            from models import User
            user_count = User.query.count()
            return user_count == 0
        except Exception:
            return True

    @staticmethod
    def _get_backup_doc():
        """Lấy backup document từ Sanity project 10."""
        project = _get_backup_project()
        if not project:
            return None
        
        try:
            groq = f'*[_id == "{FULL_BACKUP_DOC_ID}"]'
            url = f"{SanityService._get_base_url(project)}/query"
            params = {"query": groq}
            response = requests.get(url, headers=SanityService._get_headers(project), params=params, timeout=30)
            if response.status_code == 200:
                result = response.json()
                results = result.get("result", [])
                if results:
                    return results[0]
            return None
        except Exception as e:
            print(f"[DB Backup] Failed to fetch backup doc: {e}")
            return None

    @staticmethod
    def restore_from_backup():
        """Khôi phục toàn bộ database từ Sanity project 10."""
        try:
            from flask import current_app
            # Skip restore if no current_app (e.g., during import/startup before app context)
            if not current_app:
                print("[DB Backup] No application context, skipping restore")
                return False
                
            with current_app.app_context():
                from models import db, User, Order, FriendRequest, Friend, Conversation, ConversationMember, Message, Session, ApiKey, Website, MessageRead, Transaction, AuditLog
                
                if not DatabaseBackupService.is_db_empty():
                    print("[DB Backup] Database already has data, skipping restore")
                    return False

                backup = DatabaseBackupService._get_backup_doc()
                if not backup:
                    print("[DB Backup] No full backup found in Sanity")
                    return False

                backup_data = backup.get("backup_data", {})
                if not backup_data:
                    print("[DB Backup] Backup data is empty")
                    return False

                print("[DB Backup] Found full backup, starting restore...")

                # 1. Restore Users
                users_data = backup_data.get("users", [])
                restored_count = 0
                for u_data in users_data:
                    try:
                        existing = User.query.filter_by(email=u_data.get("email")).first()
                        if not existing:
                            user = User(
                                id=u_data.get("id") or str(uuid.uuid4()),
                                username=u_data.get("username", ""),
                                email=u_data.get("email", ""),
                                password_hash=u_data.get("password_hash"),
                                google_sub=u_data.get("google_sub"),
                                avatar_url=u_data.get("avatar_url"),
                                display_name=u_data.get("display_name"),
                                role=u_data.get("role", "user"),
                                package=u_data.get("package", "free"),
                                package_activated_at=datetime.fromisoformat(u_data["package_activated_at"]) if u_data.get("package_activated_at") else None,
                                theme_preference=u_data.get("theme_preference"),
                                created_at=datetime.fromisoformat(u_data.get("created_at", datetime.utcnow().isoformat())),
                                updated_at=datetime.fromisoformat(u_data.get("updated_at", datetime.utcnow().isoformat())),
                            )
                            db.session.add(user)
                            restored_count += 1
                    except Exception as e:
                        print(f"[DB Backup] Failed to restore user {u_data.get('email')}: {e}")

                db.session.commit()
                print(f"[DB Backup] Restored {restored_count}/{len(users_data)} users")

                # 2. Restore Sessions (model uses 'revoked' not 'is_active')
                sessions_data = backup_data.get("sessions", [])
                restored_sessions = 0
                for s_data in sessions_data:
                    try:
                        existing = Session.query.filter_by(token=s_data.get("token")).first()
                        if not existing:
                            session = Session(
                                id=s_data.get("id") or str(uuid.uuid4()),
                                user_id=s_data.get("user_id"),
                                token=s_data.get("token"),
                                user_agent=s_data.get("user_agent"),
                                ip_address=s_data.get("ip_address"),
                                revoked=s_data.get("revoked", False),
                                expires_at=datetime.fromisoformat(s_data["expires_at"]) if s_data.get("expires_at") else None,
                                created_at=datetime.fromisoformat(s_data.get("created_at", datetime.utcnow().isoformat())),
                            )
                            db.session.add(session)
                            restored_sessions += 1
                    except Exception as e:
                        print(f"[DB Backup] Failed to restore session: {e}")

                db.session.commit()
                print(f"[DB Backup] Restored {restored_sessions} sessions")

                # 3. Restore Orders
                orders_data = backup_data.get("orders", [])
                restored_orders = 0
                for o_data in orders_data:
                    try:
                        existing = Order.query.filter_by(id=o_data.get("id")).first()
                        if not existing:
                            order = Order(
                                id=o_data.get("id") or str(uuid.uuid4()),
                                user_id=o_data.get("user_id"),
                                package=o_data.get("package"),
                                amount=o_data.get("amount"),
                                currency=o_data.get("currency", "VND"),
                                status=o_data.get("status", "pending"),
                                payment_proof_url=o_data.get("payment_proof_url"),
                                sanity_transaction_id=o_data.get("sanity_transaction_id"),
                                admin_id=o_data.get("admin_id"),
                                reviewed_at=datetime.fromisoformat(o_data["reviewed_at"]) if o_data.get("reviewed_at") else None,
                                created_at=datetime.fromisoformat(o_data.get("created_at", datetime.utcnow().isoformat())),
                            )
                            db.session.add(order)
                            restored_orders += 1
                    except Exception as e:
                        print(f"[DB Backup] Failed to restore order: {e}")

                db.session.commit()
                print(f"[DB Backup] Restored {restored_orders} orders")

                # 4. Restore Friends
                friends_data = backup_data.get("friends", [])
                restored_friends = 0
                for f_data in friends_data:
                    try:
                        existing = Friend.query.filter_by(user_id=f_data.get("user_id"), friend_id=f_data.get("friend_id")).first()
                        if not existing:
                            friend = Friend(
                                id=f_data.get("id") or str(uuid.uuid4()),
                                user_id=f_data.get("user_id"),
                                friend_id=f_data.get("friend_id"),
                            )
                            db.session.add(friend)
                            restored_friends += 1
                    except Exception as e:
                        print(f"[DB Backup] Failed to restore friend: {e}")

                db.session.commit()
                print(f"[DB Backup] Restored {restored_friends} friends")

                # 5. Restore FriendRequests
                reqs_data = backup_data.get("friend_requests", [])
                restored_reqs = 0
                for r_data in reqs_data:
                    try:
                        existing = FriendRequest.query.filter_by(id=r_data.get("id")).first()
                        if not existing:
                            req = FriendRequest(
                                id=r_data.get("id") or str(uuid.uuid4()),
                                sender_id=r_data.get("sender_id"),
                                receiver_id=r_data.get("receiver_id"),
                                status=r_data.get("status", "PENDING"),
                                created_at=datetime.fromisoformat(r_data.get("created_at", datetime.utcnow().isoformat())),
                                updated_at=datetime.fromisoformat(r_data.get("updated_at", datetime.utcnow().isoformat())),
                            )
                            db.session.add(req)
                            restored_reqs += 1
                    except Exception as e:
                        print(f"[DB Backup] Failed to restore friend request: {e}")

                db.session.commit()
                print(f"[DB Backup] Restored {restored_reqs} friend requests")

                # 6. Restore Conversations
                convs_data = backup_data.get("conversations", [])
                restored_convs = 0
                for c_data in convs_data:
                    try:
                        existing = Conversation.query.filter_by(id=c_data.get("id")).first()
                        if not existing:
                            conv = Conversation(
                                id=c_data.get("id") or str(uuid.uuid4()),
                                created_at=datetime.fromisoformat(c_data.get("created_at", datetime.utcnow().isoformat())),
                                updated_at=datetime.fromisoformat(c_data.get("updated_at", datetime.utcnow().isoformat())),
                            )
                            db.session.add(conv)
                            restored_convs += 1
                    except Exception as e:
                        print(f"[DB Backup] Failed to restore conversation: {e}")

                db.session.commit()
                print(f"[DB Backup] Restored {restored_convs} conversations")

                # 7. Restore ConversationMembers
                members_data = backup_data.get("conversation_members", [])
                restored_members = 0
                for m_data in members_data:
                    try:
                        existing = ConversationMember.query.filter_by(conversation_id=m_data.get("conversation_id"), user_id=m_data.get("user_id")).first()
                        if not existing:
                            member = ConversationMember(
                                conversation_id=m_data.get("conversation_id"),
                                user_id=m_data.get("user_id"),
                                joined_at=datetime.fromisoformat(m_data.get("joined_at", datetime.utcnow().isoformat())),
                            )
                            db.session.add(member)
                            restored_members += 1
                    except Exception as e:
                        print(f"[DB Backup] Failed to restore member: {e}")

                db.session.commit()
                print(f"[DB Backup] Restored {restored_members} conversation members")

                # 8. Restore Messages (model does NOT have file_url)
                msgs_data = backup_data.get("messages", [])
                restored_msgs = 0
                for msg_data in msgs_data:
                    try:
                        existing = Message.query.filter_by(id=msg_data.get("id")).first()
                        if not existing:
                            msg = Message(
                                id=msg_data.get("id") or str(uuid.uuid4()),
                                conversation_id=msg_data.get("conversation_id"),
                                sender_id=msg_data.get("sender_id"),
                                content=msg_data.get("content", ""),
                                message_type=msg_data.get("message_type", "text"),
                                file_size=msg_data.get("file_size"),
                                created_at=datetime.fromisoformat(msg_data.get("created_at", datetime.utcnow().isoformat())),
                            )
                            db.session.add(msg)
                            restored_msgs += 1
                    except Exception as e:
                        print(f"[DB Backup] Failed to restore message: {e}")

                db.session.commit()
                print(f"[DB Backup] Restored {restored_msgs} messages")

                # 9. Restore API Keys
                keys_data = backup_data.get("api_keys", [])
                restored_keys = 0
                for k_data in keys_data:
                    try:
                        existing = ApiKey.query.filter_by(id=k_data.get("id")).first()
                        if not existing:
                            key = ApiKey(
                                id=k_data.get("id") or str(uuid.uuid4()),
                                user_id=k_data.get("user_id"),
                                name=k_data.get("name", "API Key"),
                                prefix=k_data.get("prefix", "ak_live_"),
                                key_hash=k_data.get("key_hash"),
                                revoked=k_data.get("revoked", False),
                                created_at=datetime.fromisoformat(k_data.get("created_at", datetime.utcnow().isoformat())),
                                last_used_at=datetime.fromisoformat(k_data["last_used_at"]) if k_data.get("last_used_at") else None,
                            )
                            db.session.add(key)
                            restored_keys += 1
                    except Exception as e:
                        print(f"[DB Backup] Failed to restore API key: {e}")

                db.session.commit()
                print(f"[DB Backup] Restored {restored_keys} API keys")

                # 10. Restore Websites
                sites_data = backup_data.get("websites", [])
                restored_sites = 0
                for w_data in sites_data:
                    try:
                        existing = Website.query.filter_by(id=w_data.get("id")).first()
                        if not existing:
                            site = Website(
                                id=w_data.get("id") or str(uuid.uuid4()),
                                user_id=w_data.get("user_id"),
                                name=w_data.get("name", "Website"),
                                domain=w_data.get("domain"),
                                redirect_url=w_data.get("redirect_url"),
                                active=w_data.get("active", True),
                                created_at=datetime.fromisoformat(w_data.get("created_at", datetime.utcnow().isoformat())),
                            )
                            db.session.add(site)
                            restored_sites += 1
                    except Exception as e:
                        print(f"[DB Backup] Failed to restore website: {e}")

                db.session.commit()
                print(f"[DB Backup] Restored {restored_sites} websites")

                # 11. Restore MessageReads
                reads_data = backup_data.get("message_reads", [])
                restored_reads = 0
                for rd_data in reads_data:
                    try:
                        existing = MessageRead.query.filter_by(id=rd_data.get("id")).first()
                        if not existing:
                            read_entry = MessageRead(
                                id=rd_data.get("id") or str(uuid.uuid4()),
                                message_id=rd_data.get("message_id"),
                                user_id=rd_data.get("user_id"),
                                read_at=datetime.fromisoformat(rd_data.get("read_at", datetime.utcnow().isoformat())),
                            )
                            db.session.add(read_entry)
                            restored_reads += 1
                    except Exception as e:
                        print(f"[DB Backup] Failed to restore message read: {e}")

                db.session.commit()
                print(f"[DB Backup] Restored {restored_reads} message reads")

                # 12. Restore Transactions
                txns_data = backup_data.get("transactions", [])
                restored_txns = 0
                for t_data in txns_data:
                    try:
                        existing = Transaction.query.filter_by(id=t_data.get("id")).first()
                        if not existing:
                            txn = Transaction(
                                id=t_data.get("id") or str(uuid.uuid4()),
                                user_id=t_data.get("user_id"),
                                order_id=t_data.get("order_id"),
                                package=t_data.get("package"),
                                amount=t_data.get("amount"),
                                currency=t_data.get("currency", "VND"),
                                status=t_data.get("status", "completed"),
                                payment_method=t_data.get("payment_method", "manual"),
                                approved_by=t_data.get("approved_by"),
                                created_at=datetime.fromisoformat(t_data.get("created_at", datetime.utcnow().isoformat())),
                            )
                            db.session.add(txn)
                            restored_txns += 1
                    except Exception as e:
                        print(f"[DB Backup] Failed to restore transaction: {e}")

                db.session.commit()
                print(f"[DB Backup] Restored {restored_txns} transactions")

                # 13. Restore AuditLogs
                logs_data = backup_data.get("audit_logs", [])
                restored_logs = 0
                for al_data in logs_data:
                    try:
                        existing = AuditLog.query.filter_by(id=al_data.get("id")).first()
                        if not existing:
                            audit_log = AuditLog(
                                id=al_data.get("id") or str(uuid.uuid4()),
                                user_id=al_data.get("user_id"),
                                event=al_data.get("event"),
                                status=al_data.get("status"),
                                user_agent=al_data.get("user_agent"),
                                ip_address=al_data.get("ip_address"),
                                details=al_data.get("details"),
                                created_at=datetime.fromisoformat(al_data.get("created_at", datetime.utcnow().isoformat())),
                            )
                            db.session.add(audit_log)
                            restored_logs += 1
                    except Exception as e:
                        print(f"[DB Backup] Failed to restore audit log: {e}")

                db.session.commit()
                print(f"[DB Backup] Restored {restored_logs} audit logs")

                total = restored_count + restored_sessions + restored_orders + restored_friends + restored_reqs + restored_convs + restored_members + restored_msgs + restored_keys + restored_sites + restored_reads + restored_txns + restored_logs
                print(f"[DB Backup] Restore complete! Total records: {total}")
                return True

        except Exception as e:
            print(f"[DB Backup] Restore failed: {e}")
            return False

    @staticmethod
    def backup_to_sanity(app=None):
        """Backup toàn bộ database lên Sanity project 10 (chạy background thread)."""
        if app is None:
            try:
                from flask import current_app
                app = current_app._get_current_object()
            except Exception:
                app = None

        thread = threading.Thread(target=DatabaseBackupService._backup_sync, args=(app,), daemon=True)
        thread.start()

    @staticmethod
    def _backup_sync(app=None):
        """Backup đồng bộ (chạy trong thread riêng)."""
        try:
            from flask import current_app
            ctx = app.app_context() if app else (current_app.app_context() if current_app else None)
            if not ctx:
                print("[DB Backup] Backup error: No application context available")
                return

            with ctx:
                from models import User, Order, FriendRequest, Friend, Conversation, ConversationMember, Message, Session, ApiKey, Website, MessageRead, Transaction, AuditLog

                project = _get_backup_project()
                if not project:
                    print("[DB Backup] No Sanity backup project configured")
                    return

                # Collect all data
                backup_data = {
                    "users": [],
                    "sessions": [],
                    "orders": [],
                    "friends": [],
                    "friend_requests": [],
                    "conversations": [],
                    "conversation_members": [],
                    "messages": [],
                    "api_keys": [],
                    "websites": [],
                    "message_reads": [],
                    "transactions": [],
                    "audit_logs": [],
                }

                for u in User.query.all():
                    backup_data["users"].append({
                        "id": u.id, "username": u.username, "email": u.email,
                        "password_hash": u.password_hash, "google_sub": u.google_sub,
                        "avatar_url": u.avatar_url, "display_name": u.display_name,
                        "role": u.role, "package": u.package,
                        "package_activated_at": u.package_activated_at.isoformat() if u.package_activated_at else None,
                        "theme_preference": u.theme_preference,
                        "created_at": u.created_at.isoformat(),
                        "updated_at": u.updated_at.isoformat() if u.updated_at else None,
                    })

                for s in Session.query.all():
                    # Session uses 'revoked' not 'is_active'
                    backup_data["sessions"].append({
                        "id": s.id, "user_id": s.user_id, "token": s.token,
                        "user_agent": s.user_agent, "ip_address": s.ip_address,
                        "revoked": s.revoked,
                        "expires_at": s.expires_at.isoformat() if s.expires_at else None,
                        "created_at": s.created_at.isoformat(),
                    })

                for o in Order.query.all():
                    backup_data["orders"].append({
                        "id": o.id, "user_id": o.user_id, "package": o.package,
                        "amount": o.amount, "currency": o.currency, "status": o.status,
                        "payment_proof_url": o.payment_proof_url,
                        "sanity_transaction_id": o.sanity_transaction_id,
                        "admin_id": o.admin_id,
                        "reviewed_at": o.reviewed_at.isoformat() if o.reviewed_at else None,
                        "created_at": o.created_at.isoformat(),
                    })

                for f in Friend.query.all():
                    backup_data["friends"].append({
                        "id": f.id, "user_id": f.user_id, "friend_id": f.friend_id,
                    })

                for r in FriendRequest.query.all():
                    backup_data["friend_requests"].append({
                        "id": r.id, "sender_id": r.sender_id, "receiver_id": r.receiver_id,
                        "status": r.status,
                        "created_at": r.created_at.isoformat(),
                        "updated_at": r.updated_at.isoformat(),
                    })

                for c in Conversation.query.all():
                    backup_data["conversations"].append({
                        "id": c.id,
                        "created_at": c.created_at.isoformat(),
                        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
                    })

                for m in ConversationMember.query.all():
                    backup_data["conversation_members"].append({
                        "conversation_id": m.conversation_id, "user_id": m.user_id,
                        "joined_at": m.joined_at.isoformat(),
                    })

                for msg in Message.query.all():
                    # Message model has NO file_url field
                    backup_data["messages"].append({
                        "id": msg.id, "conversation_id": msg.conversation_id,
                        "sender_id": msg.sender_id, "content": msg.content,
                        "message_type": msg.message_type,
                        "file_size": msg.file_size,
                        "created_at": msg.created_at.isoformat(),
                    })

                for k in ApiKey.query.all():
                    backup_data["api_keys"].append({
                        "id": k.id, "user_id": k.user_id, "name": k.name,
                        "prefix": k.prefix, "key_hash": k.key_hash, "revoked": k.revoked,
                        "created_at": k.created_at.isoformat(),
                        "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
                    })

                for w in Website.query.all():
                    backup_data["websites"].append({
                        "id": w.id, "user_id": w.user_id, "name": w.name,
                        "domain": w.domain, "redirect_url": w.redirect_url,
                        "active": w.active,
                        "created_at": w.created_at.isoformat(),
                    })

                # Backup MessageRead records
                for mr in MessageRead.query.all():
                    backup_data["message_reads"].append({
                        "id": mr.id, "message_id": mr.message_id,
                        "user_id": mr.user_id, "read_at": mr.read_at.isoformat(),
                    })

                # Backup Transaction records
                for t in Transaction.query.all():
                    backup_data["transactions"].append({
                        "id": t.id, "user_id": t.user_id, "order_id": t.order_id,
                        "package": t.package, "amount": t.amount, "currency": t.currency,
                        "status": t.status, "payment_method": t.payment_method,
                        "approved_by": t.approved_by,
                        "created_at": t.created_at.isoformat(),
                    })

                # Backup AuditLog records
                for al in AuditLog.query.all():
                    backup_data["audit_logs"].append({
                        "id": al.id, "user_id": al.user_id, "event": al.event,
                        "status": al.status, "user_agent": al.user_agent,
                        "ip_address": al.ip_address, "details": al.details,
                        "created_at": al.created_at.isoformat(),
                    })

                # Save to Sanity project 10 (upsert)
                doc = {
                    "_id": FULL_BACKUP_DOC_ID,
                    "_type": "databaseBackup",
                    "backup_data": backup_data,
                    "backup_time": datetime.utcnow().isoformat(),
                    "record_counts": {k: len(v) for k, v in backup_data.items()},
                }

                url = f"{SanityService._get_base_url(project)}/mutate"
                payload = {"mutations": [{"createOrReplace": doc}]}
                response = requests.post(url, headers=SanityService._get_headers(project), json=payload, timeout=60)
                if response.status_code == 200:
                    total = sum(len(v) for v in backup_data.values())
                    print(f"[DB Backup] Backup complete! {total} records saved to Sanity project 10")
                else:
                    print(f"[DB Backup] Backup failed: {response.text[:200]}")

        except Exception as e:
            print(f"[DB Backup] Backup error: {e}")