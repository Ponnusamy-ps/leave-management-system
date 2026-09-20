import os
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from functools import wraps

import bcrypt
import jwt
from dotenv import load_dotenv
from flask import Flask, g, jsonify, request, send_from_directory

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

PORT = int(os.getenv("PORT", "5000"))
JWT_SECRET = os.getenv("JWT_SECRET", "dev-only-change-this-secret")
DB_PATH = BASE_DIR / "database.sqlite"
PUBLIC_DIR = BASE_DIR / "public"

app = Flask(__name__, static_folder=str(PUBLIC_DIR), static_url_path="")


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH, timeout=10)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def db_one(sql, params=()):
    row = get_db().execute(sql, params).fetchone()
    return dict(row) if row else None


def db_all(sql, params=()):
    rows = get_db().execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def db_run(sql, params=()):
    db = get_db()
    cur = db.execute(sql, params)
    db.commit()
    return {"id": cur.lastrowid, "changes": cur.rowcount}


def init_database():
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.execute("PRAGMA foreign_keys = ON")

    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            full_name TEXT NOT NULL,
            email TEXT,
            role TEXT NOT NULL CHECK(role IN ('user', 'admin')),
            annual_balance INTEGER NOT NULL DEFAULT 12,
            sick_balance INTEGER NOT NULL DEFAULT 6,
            casual_balance INTEGER NOT NULL DEFAULT 6,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS leaves (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            leave_type TEXT NOT NULL CHECK(leave_type IN ('Annual', 'Sick', 'Casual')),
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            days INTEGER NOT NULL,
            reason TEXT,
            status TEXT NOT NULL DEFAULT 'Pending'
                CHECK(status IN ('Pending', 'Approved', 'Rejected', 'Cancelled')),
            admin_comment TEXT,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            reviewed_at TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    admin = db.execute(
        "SELECT id FROM users WHERE username = ?", ("admin",)
    ).fetchone()
    if not admin:
        password_hash = bcrypt.hashpw(b"admin123", bcrypt.gensalt(10)).decode("utf-8")
        db.execute(
            """INSERT INTO users
               (username, password_hash, full_name, email, role)
               VALUES (?, ?, ?, ?, 'admin')""",
            ("admin", password_hash, "System Administrator", "admin@example.com"),
        )

    employee = db.execute(
        "SELECT id FROM users WHERE username = ?", ("employee",)
    ).fetchone()
    if not employee:
        password_hash = bcrypt.hashpw(b"user123", bcrypt.gensalt(10)).decode("utf-8")
        db.execute(
            """INSERT INTO users
               (username, password_hash, full_name, email, role,
                annual_balance, sick_balance, casual_balance)
               VALUES (?, ?, ?, ?, 'user', 12, 6, 6)""",
            ("employee", password_hash, "Demo Employee", "employee@example.com"),
        )

    db.commit()
    db.close()


def create_token(user):
    payload = {
        "id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "fullName": user["full_name"],
        "exp": datetime.now(timezone.utc) + timedelta(hours=8),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def auth_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        token = header[7:] if header.startswith("Bearer ") else None

        if not token:
            return jsonify(message="Authentication required."), 401

        try:
            request.current_user = jwt.decode(
                token, JWT_SECRET, algorithms=["HS256"]
            )
        except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
            return jsonify(message="Invalid or expired token."), 401

        return view(*args, **kwargs)

    return wrapped


def admin_only(view):
    @wraps(view)
    @auth_required
    def wrapped(*args, **kwargs):
        if request.current_user.get("role") != "admin":
            return jsonify(message="Admin access required."), 403
        return view(*args, **kwargs)

    return wrapped


def valid_date_string(value):
    if not isinstance(value, str):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def calculate_days(start, end):
    if not valid_date_string(start) or not valid_date_string(end):
        return None
    start_date = date.fromisoformat(start)
    end_date = date.fromisoformat(end)
    diff = (end_date - start_date).days + 1
    return diff if diff > 0 else None


@app.post("/api/signup")
def signup():
    try:
        body = request.get_json(silent=True) or {}
        full_name = str(body.get("fullName") or "").strip()
        email = str(body.get("email") or "").strip()
        username = str(body.get("username") or "").strip()
        password = str(body.get("password") or "")

        if not full_name or not email or not username or not password:
            return jsonify(
                message="Full name, email, username and password are required."
            ), 400

        if len(full_name) < 2:
            return jsonify(message="Please enter a valid full name."), 400

        if len(username) < 3:
            return jsonify(message="Username must be at least 3 characters."), 400

        if len(password) < 6:
            return jsonify(message="Password must be at least 6 characters."), 400

        existing = db_one(
            "SELECT id FROM users WHERE username = ?",
            (username,),
        )
        if existing:
            return jsonify(message="Username already exists."), 409

        existing_email = db_one(
            "SELECT id FROM users WHERE LOWER(email) = LOWER(?)",
            (email,),
        )
        if existing_email:
            return jsonify(message="Email already exists."), 409

        password_hash = bcrypt.hashpw(
            password.encode("utf-8"), bcrypt.gensalt(10)
        ).decode("utf-8")

        result = db_run(
            """INSERT INTO users
               (username, password_hash, full_name, email, role,
                annual_balance, sick_balance, casual_balance)
               VALUES (?, ?, ?, ?, 'user', 12, 6, 6)""",
            (username, password_hash, full_name, email),
        )

        return jsonify(
            message="Account created successfully. Please login.",
            id=result["id"],
        ), 201
    except sqlite3.IntegrityError:
        return jsonify(message="Username or email already exists."), 409
    except Exception:
        app.logger.exception("Signup failed")
        return jsonify(message="Could not create account."), 500



@app.post("/api/login")
def login():
    try:
        body = request.get_json(silent=True) or {}
        username = body.get("username")
        password = body.get("password")
        role = body.get("role")

        if not username or not password or not role:
            return jsonify(
                message="Username, password and access are required."
            ), 400

        if role not in ("user", "admin"):
            return jsonify(message="Invalid access type."), 400

        user = db_one(
            "SELECT * FROM users WHERE username = ? AND role = ?",
            (str(username).strip(), role),
        )

        if not user or not bcrypt.checkpw(
            str(password).encode("utf-8"),
            user["password_hash"].encode("utf-8"),
        ):
            return jsonify(
                message="Invalid username, password or access type."
            ), 401

        token = create_token(user)

        return jsonify(
            token=token,
            user={
                "id": user["id"],
                "username": user["username"],
                "fullName": user["full_name"],
                "email": user["email"],
                "role": user["role"],
            },
        )
    except Exception:
        app.logger.exception("Login failed")
        return jsonify(message="Login failed."), 500


@app.get("/api/me")
@auth_required
def me():
    user = db_one(
        """SELECT id, username, full_name AS fullName, email, role,
                  annual_balance AS annualBalance,
                  sick_balance AS sickBalance,
                  casual_balance AS casualBalance
           FROM users WHERE id = ?""",
        (request.current_user["id"],),
    )
    if not user:
        return jsonify(message="User not found."), 404
    return jsonify(user)


@app.get("/api/leaves")
@auth_required
def leaves():
    try:
        user = request.current_user
        sql = """
            SELECT l.id, l.leave_type AS leaveType,
                   l.start_date AS startDate, l.end_date AS endDate,
                   l.days, l.reason, l.status,
                   l.admin_comment AS adminComment,
                   l.applied_at AS appliedAt,
                   l.reviewed_at AS reviewedAt,
                   u.full_name AS employeeName, u.username
            FROM leaves l
            JOIN users u ON u.id = l.user_id
        """
        params = ()
        if user["role"] != "admin":
            sql += " WHERE l.user_id = ?"
            params = (user["id"],)
        sql += " ORDER BY l.id DESC"

        return jsonify(db_all(sql, params))
    except Exception:
        app.logger.exception("Could not load leaves")
        return jsonify(message="Could not load leaves."), 500


@app.post("/api/leaves")
@auth_required
def create_leave():
    try:
        if request.current_user["role"] != "user":
            return jsonify(message="Only employees can apply for leave."), 403

        body = request.get_json(silent=True) or {}
        leave_type = body.get("leaveType")
        start_date = body.get("startDate")
        end_date = body.get("endDate")
        reason = body.get("reason")

        allowed_types = ("Annual", "Sick", "Casual")
        if (
            leave_type not in allowed_types
            or not valid_date_string(start_date)
            or not valid_date_string(end_date)
        ):
            return jsonify(
                message="Please provide a valid leave type and dates."
            ), 400

        days = calculate_days(start_date, end_date)
        if not days:
            return jsonify(
                message="End date must be on or after start date."
            ), 400

        today = date.today().isoformat()
        if start_date < today:
            return jsonify(
                message="Leave start date cannot be in the past."
            ), 400

        balance_column = {
            "Annual": "annual_balance",
            "Sick": "sick_balance",
            "Casual": "casual_balance",
        }[leave_type]

        user = db_one(
            f"SELECT {balance_column} AS balance FROM users WHERE id = ?",
            (request.current_user["id"],),
        )

        if not user or user["balance"] < days:
            available = user["balance"] if user else 0
            return jsonify(
                message=(
                    f"Insufficient {leave_type.lower()} leave balance. "
                    f"Available: {available} day(s)."
                )
            ), 400

        overlapping = db_one(
            """SELECT id FROM leaves
               WHERE user_id = ?
                 AND status IN ('Pending', 'Approved')
                 AND start_date <= ?
                 AND end_date >= ?""",
            (request.current_user["id"], end_date, start_date),
        )

        if overlapping:
            return jsonify(
                message="These dates overlap with an existing leave request."
            ), 400

        reason_value = str(reason).strip() if reason is not None else None
        reason_value = reason_value or None

        result = db_run(
            """INSERT INTO leaves
               (user_id, leave_type, start_date, end_date, days, reason)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                request.current_user["id"],
                leave_type,
                start_date,
                end_date,
                days,
                reason_value,
            ),
        )

        return jsonify(
            message="Leave application submitted.",
            id=result["id"],
        ), 201
    except Exception:
        app.logger.exception("Could not submit leave application")
        return jsonify(message="Could not submit leave application."), 500


@app.delete("/api/leaves/<int:leave_id>")
@auth_required
def delete_leave(leave_id):
    try:
        leave = db_one("SELECT * FROM leaves WHERE id = ?", (leave_id,))
        if not leave:
            return jsonify(message="Leave not found."), 404

        current_user = request.current_user

        if (
            current_user["role"] != "admin"
            and leave["user_id"] != current_user["id"]
        ):
            return jsonify(message="You cannot modify this leave."), 403

        if (
            current_user["role"] != "admin"
            and leave["status"] != "Pending"
        ):
            return jsonify(
                message="Only pending leave requests can be cancelled."
            ), 400

        if current_user["role"] == "admin":
            db_run("DELETE FROM leaves WHERE id = ?", (leave_id,))
            message = "Leave deleted."
        else:
            db_run(
                "UPDATE leaves SET status = 'Cancelled' WHERE id = ?",
                (leave_id,),
            )
            message = "Leave cancelled."

        return jsonify(message=message)
    except Exception:
        app.logger.exception("Could not update leave")
        return jsonify(message="Could not update leave."), 500


@app.patch("/api/leaves/<int:leave_id>/status")
@admin_only
def update_leave_status(leave_id):
    try:
        body = request.get_json(silent=True) or {}
        status = body.get("status")
        admin_comment = body.get("adminComment")

        if status not in ("Approved", "Rejected"):
            return jsonify(
                message="Status must be Approved or Rejected."
            ), 400

        leave = db_one("SELECT * FROM leaves WHERE id = ?", (leave_id,))
        if not leave:
            return jsonify(message="Leave not found."), 404

        if leave["status"] != "Pending":
            return jsonify(
                message="Only pending requests can be reviewed."
            ), 400

        if status == "Approved":
            balance_column = {
                "Annual": "annual_balance",
                "Sick": "sick_balance",
                "Casual": "casual_balance",
            }[leave["leave_type"]]

            user = db_one(
                f"SELECT {balance_column} AS balance FROM users WHERE id = ?",
                (leave["user_id"],),
            )

            if not user or user["balance"] < leave["days"]:
                return jsonify(
                    message="Employee no longer has enough leave balance."
                ), 400

            db_run(
                f"UPDATE users SET {balance_column} = {balance_column} - ? "
                "WHERE id = ?",
                (leave["days"], leave["user_id"]),
            )

        comment = str(admin_comment).strip() if admin_comment is not None else None
        comment = comment or None

        db_run(
            """UPDATE leaves
               SET status = ?, admin_comment = ?, reviewed_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (status, comment, leave_id),
        )

        return jsonify(message=f"Leave {status.lower()} successfully.")
    except Exception:
        app.logger.exception("Could not review leave")
        return jsonify(message="Could not review leave."), 500


@app.get("/api/admin/stats")
@admin_only
def admin_stats():
    stats = db_one("""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN status = 'Pending' THEN 1 ELSE 0 END) AS pending,
            SUM(CASE WHEN status = 'Approved' THEN 1 ELSE 0 END) AS approved,
            SUM(CASE WHEN status = 'Rejected' THEN 1 ELSE 0 END) AS rejected
        FROM leaves
    """)

    employees = db_one(
        "SELECT COUNT(*) AS count FROM users WHERE role = 'user'"
    )

    return jsonify(
        total=stats["total"] or 0,
        pending=stats["pending"] or 0,
        approved=stats["approved"] or 0,
        rejected=stats["rejected"] or 0,
        employees=employees["count"] or 0,
    )


@app.get("/api/admin/users")
@admin_only
def admin_users():
    users = db_all("""
        SELECT id, username, full_name AS fullName, email,
               annual_balance AS annualBalance,
               sick_balance AS sickBalance,
               casual_balance AS casualBalance,
               created_at AS createdAt
        FROM users
        WHERE role = 'user'
        ORDER BY id DESC
    """)
    return jsonify(users)


@app.get("/")
def index():
    index_file = PUBLIC_DIR / "index.html"
    if index_file.exists():
        return send_from_directory(PUBLIC_DIR, "index.html")
    return jsonify(
        message="Leave Management System Python backend is running.",
        frontend="No frontend was included in the uploaded Node.js project.",
        api="/api/login",
    )


@app.errorhandler(404)
def not_found(error):
    if request.path.startswith("/api/"):
        return jsonify(message="API endpoint not found."), 404
    index_file = PUBLIC_DIR / "index.html"
    if index_file.exists():
        return send_from_directory(PUBLIC_DIR, "index.html")
    return jsonify(message="Not found."), 404


init_database()

if __name__ == "__main__":
    init_database()
    print(f"Leave Management System running at http://localhost:{PORT}")
    print("Demo employee: employee / user123")
    print("Demo admin:    admin / admin123")
    app.run(host="0.0.0.0", port=PORT, debug=False)
