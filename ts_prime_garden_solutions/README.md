# TS Prime Garden Solutions

A responsive Flask website for garden services and customer enquiries. The public pages, forms, camera capture dialog and admin dashboard adapt to phone screens. Request details are stored in SQLite, optional garden photos are validated and re-encoded before private storage, and an authenticated dashboard lets the business review requests.

## Project structure

```text
ts_prime_garden_solutions/
├── app.py                         # Flask routes, validation, SQLite, email and admin auth
├── requirements.txt               # Python packages
├── instance/
│   ├── garden_requests.sqlite3     # Private customer request data (created automatically)
│   └── uploads/                    # Private re-encoded photos (created automatically)
├── static/
│   ├── style.css                   # Responsive green, white and charcoal design
│   ├── site.js                     # Photo preview and direct browser-camera capture
│   └── images/                     # Brand images
└── templates/
    ├── base.html                   # Shared navigation and footer
    ├── home.html
    ├── services.html
    ├── request_form.html
    ├── success.html
    ├── too_large.html
    ├── admin_login.html
    └── admin_dashboard.html
```

## Run it in VS Code on Windows

1. Install Python 3.11 or later and VS Code. In VS Code, choose **File → Open Folder** and open the `ts_prime_garden_solutions` folder (the one containing `app.py`).
2. Open **Terminal → New Terminal**. Create a virtual environment and install the packages:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   ```

   If PowerShell blocks activation, allow it for this terminal only and activate again:

   ```powershell
   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
   .\.venv\Scripts\Activate.ps1
   ```

3. Make a private development secret key and admin password hash. The second command asks you to enter the password without putting it in shell history:

   ```powershell
   $env:SECRET_KEY = python -c "import secrets; print(secrets.token_hex(32))"
   $env:ADMIN_PASSWORD_HASH = python -c "from getpass import getpass; from werkzeug.security import generate_password_hash; print(generate_password_hash(getpass('New admin password: ')))"
   ```

   Keep the values private. They apply to this terminal session; set them again in a new terminal. Do not commit secrets or real customer records.

4. Start the local development server:

   ```powershell
   python app.py
   ```

5. Open **http://127.0.0.1:5000**. Public pages are **Home**, **Services**, and **Request a service**. The staff dashboard is at **http://127.0.0.1:5000/admin/login**. Sign in with the password used to create `ADMIN_PASSWORD_HASH`.

The database and uploaded photos are created under `instance/`. The dashboard, CSV report and photo viewer all require an admin session. The dashboard can search requests, filter by status, record internal notes, change the admin password and export filtered requests to CSV. Existing databases gain the status and notes columns automatically at startup. The admin password hash is stored in SQLite after its first setup from `ADMIN_PASSWORD_HASH`; a password changed in the dashboard persists across restarts. Photos are restricted to JPEG, PNG or WebP input, limited to 5 MB and 20 megapixels, decoded and saved as randomly named JPEG files. CSRF protection is enabled for forms.

The request form can open the device camera in the browser, capture a still image and attach it to the request. Camera access requires the visitor's permission and a secure browser context; `http://127.0.0.1:5000` counts as localhost for local development. On a phone, use the site in its browser and allow camera access when asked. Choosing an existing photo remains available as a fallback.

The home and services pages use garden photographs from Unsplash's image CDN, so those photos need an internet connection. Replace the image URLs in `templates/home.html` and `templates/services.html` with TS Prime's own licensed photos when available.

## Email notifications

Customer requests are saved even when email is not configured or a mail server is unavailable. To send each new request notification to the admin mailbox, configure SMTP in the same PowerShell terminal before starting the app:

```powershell
$env:SMTP_HOST = "smtp.example.com"
$env:SMTP_PORT = "587"
$env:SMTP_USERNAME = "your-smtp-login"
$env:SMTP_PASSWORD = "your-smtp-app-password"
$env:SMTP_FROM = "garden@example.com"
$env:ADMIN_EMAIL = "owner@example.com"
```

Use your provider's SMTP host and an app password where available. The app uses STARTTLS on port 587. When configured, the business receives a new-request alert and the customer receives a plain-text receipt with their reference code and requested service. Set `ADMIN_EMAIL` to receive the business alert. Notification failures are written to the application log; the saved request remains available in the dashboard. The private photo is not attached to either email.

## Before production

- Configure a long random `SECRET_KEY`, `ADMIN_PASSWORD_HASH`, SMTP credentials, and `COOKIE_SECURE=1` over HTTPS in the hosting provider's secret settings. Never use the local fallback key in production.
- Use a production WSGI server and HTTPS; do not expose Flask's development server to the internet.
- Restrict dashboard access, maintain backups and define who can see customer contact details and garden photos.
- Add a privacy notice and retention policy before collecting real customer data; handle it in line with applicable privacy laws, including South Africa's POPIA.
- SQLite is suitable for local development or a small single-instance deployment with persistent disk. Use managed database storage if the app grows or runs across multiple instances.

The dashboard lists up to 500 matching requests at a time; the CSV export includes all records matching the selected filters. The app has one admin account. Additional staff users and a customer portal are not included.
