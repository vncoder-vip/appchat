import os
os.environ["FLASK_ENV"] = "test"

import unittest
import tempfile
import json
from datetime import datetime
from app import create_app
from models import db, User, Order, Friend, FriendRequest, Conversation, ConversationMember, Message, ApiKey, Website, Transaction, AuditLog, MessageRead
from services.database_backup import DatabaseBackupService
from services.chat_backup import ChatBackup
from unittest.mock import patch, MagicMock

class SystemAuditTestCase(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix='.db')
        os.close(self.db_fd)
        
        self.app = create_app(test_config={
            'TESTING': True,
            'ENV': 'test',
            'SQLALCHEMY_DATABASE_URI': f'sqlite:///{self.db_path}',
        })
        self.client = self.app.test_client()
        with self.app.app_context():
            db.drop_all()
            db.create_all()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def post_json(self, path, data, headers=None):
        return self.client.post(path, data=json.dumps(data), content_type='application/json', headers=headers)

    def get_json(self, path, headers=None):
        return self.client.get(path, content_type='application/json', headers=headers)

    # 1. DATABASE BACKUP & RESTORE INTEGRITY
    def test_database_backup_and_restore_all_tables(self):
        """Test backing up and restoring all 13 database tables."""
        with self.app.app_context():
            # Create dummy records across all models
            u1 = User(id="u1", username="user1", email="user1@gmail.com", package="pro", role="user")
            u2 = User(id="u2", username="user2", email="user2@gmail.com", package="enterprise", role="admin")
            db.session.add_all([u1, u2])
            db.session.commit()

            o1 = Order(id="o1", user_id="u1", package="pro", amount=29000, status="approved")
            f1 = Friend(id="f1", user_id="u1", friend_id="u2")
            fr1 = FriendRequest(id="fr1", sender_id="u1", receiver_id="u2", status="ACCEPTED")
            c1 = Conversation(id="c1")
            cm1 = ConversationMember(conversation_id="c1", user_id="u1")
            cm2 = ConversationMember(conversation_id="c1", user_id="u2")
            m1 = Message(id="m1", conversation_id="c1", sender_id="u1", content="Hello world")
            ak1 = ApiKey(id="ak1", user_id="u1", name="Test Key", prefix="ak_live_", key_hash="hash123")
            w1 = Website(id="w1", user_id="u1", name="My Site", domain="mysite.com")
            t1 = Transaction(id="t1", user_id="u1", package="pro", amount=29000)
            mr1 = MessageRead(id="mr1", message_id="m1", user_id="u2")
            al1 = AuditLog(id="al1", user_id="u1", event="LOGIN", status="SUCCESS")

            db.session.add_all([o1, f1, fr1, c1, cm1, cm2, m1, ak1, w1, mr1, t1, al1])
            db.session.commit()

            # Mock Sanity _get_backup_project & requests
            mock_project = {'project_id': 'proj10', 'dataset': 'production', 'api_token': 'token10'}
            mock_stored_backup = {}

            def fake_post(url, headers=None, json=None, timeout=None):
                mock_res = MagicMock()
                mock_res.status_code = 200
                if json and 'mutations' in json:
                    doc = json['mutations'][0]['createOrReplace']
                    mock_stored_backup['doc'] = doc
                return mock_res

            def fake_get(url, headers=None, params=None, timeout=None):
                mock_res = MagicMock()
                mock_res.status_code = 200
                mock_res.json.return_value = {"result": [mock_stored_backup.get('doc', {})]}
                return mock_res

            with patch('services.database_backup._get_backup_project', return_value=mock_project), \
                 patch('requests.post', side_effect=fake_post), \
                 patch('requests.get', side_effect=fake_get):
                
                # Perform sync backup
                DatabaseBackupService._backup_sync()
                self.assertIn('doc', mock_stored_backup)
                backup_doc = mock_stored_backup['doc']
                self.assertIn('backup_data', backup_doc)

                # Clear database completely
                db.drop_all()
                db.create_all()
                self.assertEqual(User.query.count(), 0)

                # Perform restore
                restored = DatabaseBackupService.restore_from_backup()
                self.assertTrue(restored)

                # Verify restored entity counts
                self.assertEqual(User.query.count(), 2)
                self.assertEqual(Order.query.count(), 1)
                self.assertEqual(Friend.query.count(), 1)
                self.assertEqual(FriendRequest.query.count(), 1)
                self.assertEqual(Conversation.query.count(), 1)
                self.assertEqual(ConversationMember.query.count(), 2)
                self.assertEqual(Message.query.count(), 1)
                self.assertEqual(ApiKey.query.count(), 1)
                self.assertEqual(Website.query.count(), 1)
                self.assertEqual(MessageRead.query.count(), 1)
                self.assertEqual(Transaction.query.count(), 1)
                self.assertEqual(AuditLog.query.count(), 1)

                restored_u1 = User.query.get("u1")
                self.assertEqual(restored_u1.username, "user1")
                self.assertEqual(restored_u1.package, "pro")

                restored_m1 = Message.query.get("m1")
                self.assertEqual(restored_m1.content, "Hello world")

    # 2. REAL-TIME CHAT BACKUP & RESTORE INTEGRITY
    def test_chat_backup_message_and_conversation(self):
        """Test ChatBackup module for individual messages and batch queries."""
        mock_project = {'project_id': 'proj10', 'dataset': 'production', 'api_token': 'token10'}
        
        with self.app.app_context():
            u1 = User(id="u1", username="user1", email="user1@gmail.com")
            c1 = Conversation(id="c1")
            m1 = Message(id="msg1", conversation_id="c1", sender_id="u1", content="Realtime backup test")

            def fake_post(url, headers=None, json=None, timeout=None):
                mock_res = MagicMock()
                mock_res.status_code = 200
                return mock_res

            with patch('services.chat_backup._get_backup_project', return_value=mock_project), \
                 patch('requests.post', side_effect=fake_post):
                
                doc_id = ChatBackup.backup_message(m1)
                self.assertEqual(doc_id, "chat-msg-msg1")

                conv_doc_id = ChatBackup.backup_conversation(c1, ["u1"])
                self.assertEqual(conv_doc_id, "chat-conv-c1")

    # 3. END-TO-END REGISTRATION & SOCIAL API SUITE
    def test_social_features_end_to_end(self):
        """Test register users -> send friend request -> accept -> create conversation -> send message."""
        # 1. Register User A
        res_a = self.post_json('/api/auth/register', {
            "username": "UserA", "email": "usera@gmail.com", "password": "password123"
        })
        token_a = res_a.get_json()['accessToken']
        id_a = res_a.get_json()['user']['id']

        # 2. Register User B
        res_b = self.post_json('/api/auth/register', {
            "username": "UserB", "email": "userb@gmail.com", "password": "password123"
        })
        token_b = res_b.get_json()['accessToken']
        id_b = res_b.get_json()['user']['id']

        # 3. User A searches for User B
        search_res = self.get_json(f'/api/users/search?q=UserB', headers={"Authorization": f"Bearer {token_a}"})
        self.assertEqual(search_res.status_code, 200)
        self.assertEqual(len(search_res.get_json()['users']), 1)

        # 4. User A sends Friend Request to User B
        freq_res = self.post_json('/api/friends/request', {"receiver_id": id_b}, headers={"Authorization": f"Bearer {token_a}"})
        self.assertEqual(freq_res.status_code, 201)
        req_id = freq_res.get_json()['friend_request']['id']

        # 5. User B accepts Friend Request (which automatically creates the conversation)
        accept_res = self.post_json(f'/api/friends/accept/{req_id}', {}, headers={"Authorization": f"Bearer {token_b}"})
        self.assertEqual(accept_res.status_code, 200)
        conv_id = accept_res.get_json()['conversation']['id']

        # 7. User A sends a message in conversation
        msg_res = self.post_json('/api/messages', {
            "conversation_id": conv_id,
            "content": "Hello B from A!"
        }, headers={"Authorization": f"Bearer {token_a}"})
        self.assertEqual(msg_res.status_code, 201)

        # 8. User B fetches messages
        msgs_res = self.get_json(f'/api/messages/{conv_id}', headers={"Authorization": f"Bearer {token_b}"})
        self.assertEqual(msgs_res.status_code, 200)
        self.assertEqual(len(msgs_res.get_json()['messages']), 1)
        self.assertEqual(msgs_res.get_json()['messages'][0]['content'], "Hello B from A!")

if __name__ == '__main__':
    unittest.main()
