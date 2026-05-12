import os
import uuid
from datetime import datetime

from werkzeug.security import check_password_hash, generate_password_hash

from pbx_portal.sources import _database_url_from_env, ensure_portal_schema


class AuthService:
    def __init__(self, database_url):
        self.database_url = database_url

    @classmethod
    def from_env(cls):
        database_url = _database_url_from_env()
        if not database_url:
            raise RuntimeError("DATABASE_URL or POSTGRES_* settings are required for authentication")
        ensure_portal_schema(database_url)
        service = cls(database_url)
        service.ensure_bootstrap_admin()
        return service

    def ensure_bootstrap_admin(self):
        admin_username = os.getenv("ADMIN_USERNAME", "admin")
        admin_password = os.getenv("ADMIN_PASSWORD", "admin123")
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM portal_users")
                count = cursor.fetchone()[0]
                if count:
                    return
                cursor.execute(
                    """
                    INSERT INTO portal_users (username, password_hash, role, full_name, enabled)
                    VALUES (%s, %s, 'admin', %s, TRUE)
                    """,
                    (admin_username, generate_password_hash(admin_password), "Administrator"),
                )
            conn.commit()

    def authenticate(self, username, password):
        user = self.get_user_by_username(username)
        if not user or not user["enabled"]:
            return None
        if not check_password_hash(user["password_hash"], password):
            return None
        self.touch_login(user["id"])
        return _public_user(user)

    def get_user_by_id(self, user_id):
        parsed_user_id = _parse_user_id(user_id)
        with self._connect(row_factory=True) as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, username, password_hash, role, full_name, enabled, last_login_at
                    FROM portal_users
                    WHERE id = %s
                    """,
                    (parsed_user_id,),
                )
                row = cursor.fetchone()
                return dict(row) if row else None

    def get_user_by_username(self, username):
        with self._connect(row_factory=True) as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, username, password_hash, role, full_name, enabled, last_login_at
                    FROM portal_users
                    WHERE lower(username) = lower(%s)
                    """,
                    (username,),
                )
                row = cursor.fetchone()
                return dict(row) if row else None

    def list_users(self):
        with self._connect(row_factory=True) as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, username, role, full_name, enabled, last_login_at, created_at
                    FROM portal_users
                    ORDER BY username
                    """
                )
                return [_serialize_user(dict(row)) for row in cursor.fetchall()]

    def create_user(self, username, password, role="user", full_name=""):
        role = role if role in {"admin", "user"} else "user"
        username = (username or "").strip()
        if not username or not password:
            raise ValueError("Username and password are required")
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO portal_users (username, password_hash, role, full_name, enabled)
                    VALUES (%s, %s, %s, %s, TRUE)
                    RETURNING id
                    """,
                    (username, generate_password_hash(password), role, (full_name or "").strip() or username),
                )
                user_id = cursor.fetchone()[0]
            conn.commit()
        return _public_user(self.get_user_by_id(user_id))

    def update_user(self, user_id, username=None, full_name=None, role=None, enabled=None):
        parsed_user_id = _parse_user_id(user_id)
        current = self.get_user_by_id(parsed_user_id)
        if not current:
            raise ValueError("User not found")

        next_username = (username if username is not None else current["username"]).strip()
        next_full_name = (full_name if full_name is not None else current["full_name"]).strip()
        next_role = role if role is not None else current["role"]
        next_enabled = bool(enabled) if enabled is not None else current["enabled"]

        if not next_username:
            raise ValueError("Username is required")
        if next_role not in {"admin", "user"}:
            raise ValueError("Role must be admin or user")
        if not next_full_name:
            next_full_name = next_username

        if current["role"] == "admin" and current["enabled"]:
            is_demoting = next_role != "admin"
            is_disabling = not next_enabled
            if (is_demoting or is_disabling) and self._is_last_enabled_admin(user_id):
                raise ValueError("At least one enabled admin must remain")

        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE portal_users
                    SET username = %s,
                        full_name = %s,
                        role = %s,
                        enabled = %s,
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (next_username, next_full_name, next_role, next_enabled, parsed_user_id),
                )
            conn.commit()
        return _public_user(self.get_user_by_id(parsed_user_id))

    def set_password(self, user_id, password):
        parsed_user_id = _parse_user_id(user_id)
        if not password:
            raise ValueError("Password is required")
        current = self.get_user_by_id(parsed_user_id)
        if not current:
            raise ValueError("User not found")
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE portal_users
                    SET password_hash = %s,
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (generate_password_hash(password), parsed_user_id),
                )
            conn.commit()
        return True

    def delete_user(self, user_id):
        parsed_user_id = _parse_user_id(user_id)
        current = self.get_user_by_id(parsed_user_id)
        if not current:
            raise ValueError("User not found")
        if current["role"] == "admin" and current["enabled"] and self._is_last_enabled_admin(parsed_user_id):
            raise ValueError("At least one enabled admin must remain")

        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM portal_users WHERE id = %s", (parsed_user_id,))
            conn.commit()
        return True

    def touch_login(self, user_id):
        parsed_user_id = _parse_user_id(user_id)
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute("UPDATE portal_users SET last_login_at = NOW() WHERE id = %s", (parsed_user_id,))
            conn.commit()

    def _connect(self, row_factory=False):
        import psycopg
        from psycopg.rows import dict_row

        kwargs = {"row_factory": dict_row} if row_factory else {}
        return psycopg.connect(self.database_url, **kwargs)

    def _is_last_enabled_admin(self, user_id):
        parsed_user_id = _parse_user_id(user_id)
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COUNT(*) FROM portal_users
                    WHERE role = 'admin' AND enabled = TRUE AND id <> %s
                    """,
                    (parsed_user_id,),
                )
                return cursor.fetchone()[0] == 0


def _public_user(user):
    return {
        "id": str(user["id"]),
        "username": user["username"],
        "role": user["role"],
        "full_name": user["full_name"],
        "enabled": user["enabled"],
    }


def _serialize_user(user):
    serialized = _public_user(user)
    last_login = user.get("last_login_at")
    created = user.get("created_at")
    serialized["last_login_at"] = last_login.isoformat() if isinstance(last_login, datetime) else last_login
    serialized["created_at"] = created.isoformat() if isinstance(created, datetime) else created
    return serialized


def _parse_user_id(user_id):
    try:
        return uuid.UUID(str(user_id))
    except (TypeError, ValueError, AttributeError):
        raise ValueError("Invalid user id")
