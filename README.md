# Leave Management System — Python + Full Frontend

This is the complete Python backend + supplied frontend in one project.

## Stack
- Frontend: HTML, CSS, JavaScript (kept from the supplied files)
- Backend: Python + Flask
- Database: SQLite
- Authentication: JWT
- Password hashing: bcrypt

## Frontend
The supplied login/dashboard files are included without redesigning them:
- `public/index.html`
- `public/style.css`
- `public/app.js`
- `public/dashboard.html`
- `public/dashboard.css`
- `public/dashboard.js`
- `public/assets/dilogo.jpg`

The supplied logo image is copied unchanged into the exact asset path used by the HTML.

## Sign Up
The frontend already contains a Sign Up tab. The Python backend now provides:
- `POST /api/signup`
- full name, email, username, password
- duplicate username/email checks
- password minimum validation
- new accounts are created as employee/user accounts with 12 Annual, 6 Sick and 6 Casual days

## Run on Windows
1. Open this folder in Command Prompt / PowerShell.
2. Create virtual environment:
   `python -m venv .venv`
3. Activate:
   `.venv\Scripts\activate`
4. Install packages:
   `pip install -r requirements.txt`
5. Copy `.env.example` to `.env`:
   `copy .env.example .env`
6. Start:
   `python app.py`
7. Open:
   `http://localhost:5000`

## Demo accounts
- Admin: `admin` / `admin123`
- Employee: `employee` / `user123`

## Important
The frontend calls `/api/login`, `/api/signup`, `/api/me`, `/api/leaves`, `/api/admin/stats`, and `/api/admin/users`. These endpoints are implemented by the Python Flask backend in this project.

No Node.js runtime is required.
