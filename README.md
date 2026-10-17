# SecureNotes

A Flask web application that demonstrates facial recognition login,
role-based access to notes, and group messaging.

Developed as an academic project to explore biometric authentication,
access control, and full-stack web development.

## Features

- Webcam-based user registration and facial recognition login.
- Three access levels: LEVEL1, LEVEL2, and LEVEL3.
- Note content displayed according to the user's access level.
- Note search and category filtering.
- Administrator dashboard for managing users, roles, and notes.
- Note pinning and file attachments.
- Group chat with membership management and attachments.
- Login history with timestamps, IP addresses, and face-match distances.

## Technologies

- Python
- Flask
- Flask-SQLAlchemy
- SQLite
- face_recognition
- HTML, CSS, and JavaScript
- Browser camera API

## Project Structure

    Secure-Notes/
    ├── app.py
    ├── requirements.txt
    ├── .gitignore
    ├── templates/
    │   ├── admin_dashboard.html
    │   ├── admin.html
    │   ├── chat_groups.html
    │   ├── index.html
    │   ├── note_detail.html
    │   └── success.html
    └── static/
        └── js/
            └── script.js

## Configuration and Data

The application reads its Flask session signing key from the
SECRET_KEY environment variable. This variable must be configured
before starting the application.

Local databases, uploaded photos, biometric face encodings,
and user attachments are not included in this repository.

The application creates its database tables and upload directories
during initialization.

The user interface is currently in Romanian.

## Security Limitations

This is an educational prototype, not a production-ready authentication
system.

Known limitations include:

- Administrator privileges are currently assigned based on the
  reserved username "admin".
- No explicit liveness detection or anti-spoofing mechanism is implemented.
- Uploaded files are stored under the static directory and are not
  protected by per-request authorization checks.
- CSRF protection is not implemented in the provided application code.
- Note formatting requires additional HTML escaping or sanitization.
- Debug mode is enabled in the local development entry point.

Do not expose this application to the public internet or use it
to store sensitive information without further security improvements.

## Future Improvements

- Replace username-based administrator assignment with controlled
  administrator provisioning.
- Add liveness detection and stronger authentication safeguards.
- Serve private attachments through authenticated, authorized routes.
- Add CSRF protection and safer content formatting.
- Add automated tests and database migrations.
- Document and verify installation in a clean environment.
