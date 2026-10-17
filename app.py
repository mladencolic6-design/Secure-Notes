import os
import uuid
import pickle
import datetime
from flask import Flask, request, jsonify, render_template, session, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
import face_recognition
from markupsafe import Markup

app = Flask(__name__)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
ATTACH_FOLDER = os.path.join(UPLOAD_FOLDER, 'attachments')
CHAT_ATTACH_FOLDER = os.path.join(UPLOAD_FOLDER, 'chat_attachments')
DB_PATH = os.path.join(BASE_DIR, 'face_login.db')

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(ATTACH_FOLDER, exist_ok=True)
os.makedirs(CHAT_ATTACH_FOLDER, exist_ok=True)

app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{DB_PATH}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = os.environ.get("SECRET_KEY")

if not app.secret_key:
    raise RuntimeError(
        "Set the SECRET_KEY environment variable before starting the app."
    )

db = SQLAlchemy(app)

ADMIN_NAME = "admin"
FACE_MATCH_THRESHOLD = 0.55

ALLOWED_CHAT_EXTENSIONS = {
    'png', 'jpg', 'jpeg', 'gif', 'webp',
    'pdf', 'doc', 'docx', 'txt', 'xlsx', 'xls', 'zip'
}


# ---------- HELPERS ----------

def allowed_chat_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_CHAT_EXTENSIONS


def get_user_role(user):
    if not user:
        return 'LEVEL1'
    return user.role or 'LEVEL1'


def role_to_int(role):
    return {'LEVEL1': 1, 'LEVEL2': 2, 'LEVEL3': 3}.get(role or 'LEVEL1', 1)


def can_view_note(user_role, note_role):
    if not note_role:
        return True
    return role_to_int(user_role) >= role_to_int(note_role)


def current_user_obj():
    user_name = session.get('user_name')
    if not user_name:
        return None
    return User.query.filter_by(name=user_name).first()


def build_note_content_for_role(note, user_role):
    parts = []

    if note.content_level1:
        parts.append(note.content_level1.strip())

    if role_to_int(user_role) >= 2 and note.content_level2:
        parts.append(note.content_level2.strip())

    if role_to_int(user_role) >= 3 and note.content_level3:
        parts.append(note.content_level3.strip())

    return "\n\n".join([p for p in parts if p]).strip()


def mask_note_content(user_role, text, note_role):
    if can_view_note(user_role, note_role):
        return text
    hidden = '█' * max(24, min(len(text or ''), 140))
    return f"{hidden}\n\nConținutul acestei notițe nu este disponibil pentru nivelul dumneavoastră de acces."


def simple_format(text):
    lines = (text or "").splitlines()
    html_lines = []

    for line in lines:
        stripped = line.rstrip()

        if not stripped:
            html_lines.append("<p></p>")
            continue

        if stripped.startswith("# "):
            html_lines.append(f"<h2>{stripped[2:]}</h2>")
        elif stripped.startswith("[ ] "):
            html_lines.append(f'<p><label><input type="checkbox" disabled> {stripped[4:]}</label></p>')
        elif stripped.startswith("[x] ") or stripped.startswith("[X] "):
            html_lines.append(f'<p><label><input type="checkbox" disabled checked> {stripped[4:]}</label></p>')
        elif stripped.startswith("- "):
            html_lines.append(f"<p>• {stripped[2:]}</p>")
        else:
            html_lines.append(f"<p>{stripped}</p>")

    return Markup("\n".join(html_lines))


app.jinja_env.filters['simple_format'] = simple_format


# ---------- MODELI ----------

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    photo_filename = db.Column(db.String(200), nullable=False)
    face_encoding = db.Column(db.LargeBinary, nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    role = db.Column(db.String(20), default='LEVEL1')
    registered_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    login_logs = db.relationship('LoginLog', backref='user', lazy=True)
    notes = db.relationship('Note', backref='author', lazy=True)


class LoginLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    success = db.Column(db.Boolean, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    ip_address = db.Column(db.String(50))
    distance = db.Column(db.Float, nullable=True)


class Note(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content_level1 = db.Column(db.Text, default='')
    content_level2 = db.Column(db.Text, default='')
    content_level3 = db.Column(db.Text, default='')
    category = db.Column(db.String(50), default='Generale')
    required_role = db.Column(db.String(20), nullable=True)
    is_pinned = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    author_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)


class NoteAttachment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    note_id = db.Column(db.Integer, db.ForeignKey('note.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    original_name = db.Column(db.String(255), nullable=False)
    content_type = db.Column(db.String(100), nullable=False)


Note.attachments = db.relationship('NoteAttachment', backref='note', lazy=True)


class ChatGroup(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    creator = db.relationship('User', backref='created_groups')


class ChatGroupMember(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('chat_group.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    group = db.relationship('ChatGroup', backref='members')
    user = db.relationship('User')


class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('chat_group.id'), nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    text = db.Column(db.Text, nullable=False, default='')
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    group = db.relationship('ChatGroup', backref='messages')
    sender = db.relationship('User')


class ChatAttachment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey('chat_message.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    original_name = db.Column(db.String(255), nullable=False)
    content_type = db.Column(db.String(100), nullable=False)

    message = db.relationship('ChatMessage', backref='attachments')


# ---------- INIT / MIGRACIJE ----------

def ensure_schema():
    with app.app_context():
        db.create_all()

        inspector = db.inspect(db.engine)

        user_columns = [c["name"] for c in inspector.get_columns('user')]
        if 'is_admin' not in user_columns:
            db.session.execute(db.text("ALTER TABLE user ADD COLUMN is_admin BOOLEAN DEFAULT 0"))
            db.session.commit()
        if 'role' not in user_columns:
            db.session.execute(db.text("ALTER TABLE user ADD COLUMN role VARCHAR(20) DEFAULT 'LEVEL1'"))
            db.session.commit()

        log_columns = [c["name"] for c in inspector.get_columns('login_log')]
        if 'distance' not in log_columns:
            db.session.execute(db.text("ALTER TABLE login_log ADD COLUMN distance FLOAT"))
            db.session.commit()

        tables = inspector.get_table_names()
        if 'note' not in tables:
            Note.__table__.create(db.engine)
        if 'note_attachment' not in tables:
            NoteAttachment.__table__.create(db.engine)
        if 'chat_group' not in tables:
            ChatGroup.__table__.create(db.engine)
        if 'chat_group_member' not in tables:
            ChatGroupMember.__table__.create(db.engine)
        if 'chat_message' not in tables:
            ChatMessage.__table__.create(db.engine)
        if 'chat_attachment' not in tables:
            ChatAttachment.__table__.create(db.engine)

        note_columns = [c["name"] for c in inspector.get_columns('note')]
        if 'content_level1' not in note_columns:
            db.session.execute(db.text("ALTER TABLE note ADD COLUMN content_level1 TEXT DEFAULT ''"))
            db.session.commit()
        if 'content_level2' not in note_columns:
            db.session.execute(db.text("ALTER TABLE note ADD COLUMN content_level2 TEXT DEFAULT ''"))
            db.session.commit()
        if 'content_level3' not in note_columns:
            db.session.execute(db.text("ALTER TABLE note ADD COLUMN content_level3 TEXT DEFAULT ''"))
            db.session.commit()


def fix_admin_flags():
    with app.app_context():
        users = User.query.all()
        for user in users:
            is_admin = (user.name.lower() == ADMIN_NAME.lower())
            user.is_admin = is_admin
            if is_admin:
                user.role = 'LEVEL3'
            if not user.role:
                user.role = 'LEVEL1'
        db.session.commit()


def seed_notes():
    with app.app_context():
        if Note.query.count() > 0:
            return

        admin_user = User.query.filter(db.func.lower(User.name) == ADMIN_NAME.lower()).first()

        demo_notes = [
            {
                'title': 'Bine ați venit în SecureNotes',
                'content_level1': '# Bine ați venit\n\nAcesta este conținutul de bază pentru LEVEL1.\n\n[ ] Familiarizați-vă cu interfața',
                'content_level2': '# Supliment LEVEL2\n\nAici sunt informații interne suplimentare pentru LEVEL2.',
                'content_level3': '# Supliment LEVEL3\n\nAici sunt informațiile complete de administrare pentru LEVEL3.',
                'category': 'Generale',
                'required_role': None,
                'is_pinned': True,
            },
            {
                'title': 'Planul de dezvoltare al aplicației',
                'content_level1': '# Plan\n\nPrezentare generală a planului de dezvoltare.',
                'content_level2': '[ ] Adăugarea atașamentelor la notițe\n[ ] Îmbunătățirea formatării conținutului',
                'content_level3': '[ ] Audit de securitate\n[ ] Adăugarea controalelor de administrare',
                'category': 'Serviciu',
                'required_role': None,
                'is_pinned': False,
            }
        ]

        for item in demo_notes:
            db.session.add(
                Note(
                    author_id=admin_user.id if admin_user else None,
                    **item
                )
            )

        db.session.commit()


# ---------- RUTE: AUTH ----------

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/register', methods=['POST'])
def register():
    name = request.form.get('name', '').strip()

    if not name:
        return jsonify({'success': False, 'message': 'Numele este obligatoriu.'}), 400

    if 'photo' not in request.files or request.files['photo'].filename == '':
        return jsonify({'success': False, 'message': 'Fotografia este obligatorie.'}), 400

    existing_user = User.query.filter_by(name=name).first()
    if existing_user:
        return jsonify({'success': False, 'message': 'Există deja un utilizator cu acest nume.'}), 400

    photo = request.files['photo']
    safe_name = secure_filename(name)
    filename = f"{datetime.date.today()}_{safe_name}_{uuid.uuid4().hex[:8]}.jpg"
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    photo.save(filepath)

    image = face_recognition.load_image_file(filepath)
    encodings = face_recognition.face_encodings(image)

    if len(encodings) == 0:
        os.remove(filepath)
        return jsonify({'success': False, 'message': 'Nu a fost detectată nicio față în fotografie.'}), 400

    encoding_blob = pickle.dumps(encodings[0])
    is_admin = (name.lower() == ADMIN_NAME.lower())

    user = User(
        name=name,
        photo_filename=filename,
        face_encoding=encoding_blob,
        is_admin=is_admin,
        role='LEVEL3' if is_admin else 'LEVEL1'
    )
    db.session.add(user)
    db.session.commit()

    return jsonify({
        'success': True,
        'name': name,
        'is_admin': is_admin,
        'message': 'Înregistrare reușită.'
    })


@app.route('/login', methods=['POST'])
def login():
    session.clear()

    if 'photo' not in request.files or request.files['photo'].filename == '':
        return jsonify({'success': False, 'message': 'Fotografia este obligatorie.'}), 400

    photo = request.files['photo']
    login_filename = os.path.join(UPLOAD_FOLDER, f'login_{uuid.uuid4().hex[:8]}.jpg')
    photo.save(login_filename)

    try:
        login_image = face_recognition.load_image_file(login_filename)
        login_encodings = face_recognition.face_encodings(login_image)

        if len(login_encodings) == 0:
            db.session.add(LoginLog(success=False, ip_address=request.remote_addr, distance=None))
            db.session.commit()
            return jsonify({'success': False, 'message': 'Nu a fost detectată nicio față.'}), 400

        users = User.query.all()
        best_match_user = None
        best_distance = 999.0

        for login_encoding in login_encodings:
            for user in users:
                stored_encoding = pickle.loads(user.face_encoding)
                distance = face_recognition.face_distance([stored_encoding], login_encoding)[0]
                if distance < best_distance:
                    best_distance = distance
                    best_match_user = user

        if best_match_user and best_distance <= FACE_MATCH_THRESHOLD:
            real_is_admin = (best_match_user.name.lower() == ADMIN_NAME.lower())
            best_match_user.is_admin = real_is_admin
            if real_is_admin:
                best_match_user.role = 'LEVEL3'
            if not best_match_user.role:
                best_match_user.role = 'LEVEL1'
            db.session.commit()

            log = LoginLog(
                user_id=best_match_user.id,
                success=True,
                ip_address=request.remote_addr,
                distance=float(best_distance)
            )
            db.session.add(log)
            db.session.commit()

            session['user_name'] = best_match_user.name
            session['is_admin'] = real_is_admin

            return jsonify({
                'success': True,
                'name': best_match_user.name,
                'is_admin': real_is_admin,
                'distance': round(float(best_distance), 4),
                'message': f'Autentificare reușită. Distanță: {best_distance:.4f}',
                'redirect_url': url_for('admin_dashboard') if real_is_admin else url_for('success')
            })

        db.session.add(LoginLog(success=False, ip_address=request.remote_addr, distance=float(best_distance)))
        db.session.commit()

        return jsonify({
            'success': False,
            'message': f'Fața nu a fost recunoscută. Cea mai bună distanță: {best_distance:.4f}'
        })
    finally:
        if os.path.exists(login_filename):
            os.remove(login_filename)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))


# ---------- RUTE: NOTE USER ----------

@app.route('/success')
def success():
    user = current_user_obj()
    if not user:
        return redirect(url_for('index'))

    user_role = get_user_role(user)
    selected_category = request.args.get('category', '').strip()
    search_query = request.args.get('q', '').strip()

    query = Note.query.order_by(Note.is_pinned.desc(), Note.created_at.desc())
    if selected_category:
        query = query.filter_by(category=selected_category)

    notes = query.all()
    categories = [row[0] for row in db.session.query(Note.category).distinct().order_by(Note.category).all()]

    notes_view = []
    for note in notes:
        built_content = build_note_content_for_role(note, user_role)

        if search_query:
            whole = f"{note.title}\n{built_content}".lower()
            if search_query.lower() not in whole:
                continue

        text_for_preview = built_content[:180] + ('...' if len(built_content) > 180 else '')
        preview_raw = mask_note_content(user_role, text_for_preview, note.required_role)

        notes_view.append({
            'note': note,
            'preview': preview_raw,
            'can_open': can_view_note(user_role, note.required_role)
        })

    return render_template(
        'success.html',
        user_name=user.name,
        user_role=user_role,
        notes_view=notes_view,
        categories=categories,
        selected_category=selected_category,
        search_query=search_query
    )


@app.route('/notes/<int:note_id>')
def note_detail(note_id):
    user = current_user_obj()
    if not user:
        return redirect(url_for('index'))

    note = Note.query.get_or_404(note_id)
    user_role = get_user_role(user)

    built_content = build_note_content_for_role(note, user_role)
    visible_content = mask_note_content(user_role, built_content, note.required_role)

    return render_template(
        'note_detail.html',
        note=note,
        user=user,
        user_role=user_role,
        visible_content=visible_content
    )

@app.route('/admin/users/<int:user_id>/delete', methods=['POST'])
def delete_user(user_id):
    current = current_user_obj()

    if not current:
        return redirect(url_for('index'))

    if not session.get('is_admin'):
        return redirect(url_for('success'))

    target_user = User.query.get_or_404(user_id)

    if target_user.is_admin:
        return redirect(url_for('admin_dashboard'))

    if target_user.id == current.id:
        return redirect(url_for('admin_dashboard'))

    db.session.delete(target_user)
    db.session.commit()

    return redirect(url_for('admin_dashboard'))

# ---------- RUTE: ADMIN ----------

@app.route('/admin-dashboard')
def admin_dashboard():
    user = current_user_obj()
    if not user:
        return redirect(url_for('index'))
    if not session.get('is_admin'):
        return redirect(url_for('success'))

    users = User.query.order_by(User.registered_at.desc()).all()
    logs = LoginLog.query.order_by(LoginLog.timestamp.desc()).all()
    notes = Note.query.order_by(Note.is_pinned.desc(), Note.created_at.desc()).all()

    stats = {
        'users_count': User.query.count(),
        'success_count': LoginLog.query.filter_by(success=True).count(),
        'failed_count': LoginLog.query.filter_by(success=False).count(),
        'notes_count': Note.query.count(),
    }

    categories = [row[0] for row in db.session.query(Note.category).distinct().order_by(Note.category).all()]

    return render_template(
        'admin_dashboard.html',
        current_user=user,
        admin_name=user.name,
        users=users,
        logs=logs,
        notes=notes,
        stats=stats,
        categories=categories
    )



@app.route('/admin/notes/create', methods=['POST'])
def create_note():
    user = current_user_obj()
    if not user or not session.get('is_admin'):
        return redirect(url_for('index'))

    title = request.form.get('title', '').strip()
    content_level1 = request.form.get('content_level1', '').strip()
    content_level2 = request.form.get('content_level2', '').strip()
    content_level3 = request.form.get('content_level3', '').strip()
    category = request.form.get('category', 'Generale').strip() or 'Generale'
    required_role = request.form.get('required_role', '').strip() or None
    is_pinned = request.form.get('is_pinned') == 'on'

    if not title or not content_level1:
        return redirect(url_for('admin_dashboard'))

    note = Note(
        title=title,
        content_level1=content_level1,
        content_level2=content_level2,
        content_level3=content_level3,
        category=category,
        required_role=required_role,
        is_pinned=is_pinned,
        author_id=user.id
    )
    db.session.add(note)
    db.session.commit()

    file = request.files.get('attachment')
    if file and file.filename:
        safe_name = secure_filename(file.filename)
        fname = f"{note.id}_{uuid.uuid4().hex}_{safe_name}"
        path = os.path.join(ATTACH_FOLDER, fname)
        file.save(path)

        attachment = NoteAttachment(
            note_id=note.id,
            filename=fname,
            original_name=file.filename,
            content_type=file.mimetype
        )
        db.session.add(attachment)
        db.session.commit()

    return redirect(url_for('admin_dashboard'))


@app.route('/admin/notes/<int:note_id>/toggle-pin', methods=['POST'])
def toggle_pin(note_id):
    user = current_user_obj()
    if not user or not session.get('is_admin'):
        return redirect(url_for('index'))

    note = Note.query.get_or_404(note_id)
    note.is_pinned = not note.is_pinned
    db.session.commit()
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/notes/<int:note_id>/delete', methods=['POST'])
def delete_note(note_id):
    user = current_user_obj()
    if not user or not session.get('is_admin'):
        return redirect(url_for('index'))

    note = Note.query.get_or_404(note_id)
    for att in note.attachments:
        path = os.path.join(ATTACH_FOLDER, att.filename)
        if os.path.exists(path):
            os.remove(path)
        db.session.delete(att)

    db.session.delete(note)
    db.session.commit()
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/users/<int:user_id>/role', methods=['POST'])
def update_user_role(user_id):
    admin = current_user_obj()
    if not admin or not session.get('is_admin'):
        return redirect(url_for('index'))

    new_role = request.form.get('role', 'LEVEL1').strip()
    if new_role not in ('LEVEL1', 'LEVEL2', 'LEVEL3'):
        return redirect(url_for('admin_dashboard'))

    user = User.query.get_or_404(user_id)
    user.role = new_role
    db.session.commit()
    return redirect(url_for('admin_dashboard'))


# ---------- RUTE: CHAT ----------

@app.route('/chat')
def chat():
    user = current_user_obj()
    if not user:
        return redirect(url_for('index'))

    user_role = get_user_role(user)

    if user_role == 'LEVEL3':
        groups = ChatGroup.query.order_by(ChatGroup.created_at.desc()).all()
    else:
        groups = (ChatGroup.query
                  .join(ChatGroupMember)
                  .filter(ChatGroupMember.user_id == user.id)
                  .order_by(ChatGroup.created_at.desc())
                  .all())

    group_id = request.args.get('group_id', type=int)
    current_group = None
    messages = []
    group_members = []

    if groups:
        if group_id is None or not any(g.id == group_id for g in groups):
            current_group = groups[0]
        else:
            current_group = next(g for g in groups if g.id == group_id)

        messages = (ChatMessage.query
                    .filter_by(group_id=current_group.id)
                    .order_by(ChatMessage.created_at.asc())
                    .all())

        group_members = sorted(
            [m for m in current_group.members if m.user is not None],
            key=lambda m: (m.user.name or '').lower()
        )
    all_users = []
    if user_role == 'LEVEL3':
        all_users = User.query.order_by(User.name.asc()).all()

    return render_template(
        'chat_groups.html',
        user=user,
        user_role=user_role,
        groups=groups,
        current_group=current_group,
        messages=messages,
        all_users=all_users,
        group_members=group_members
    )


@app.route('/chat/send', methods=['POST'])
def chat_send():
    user = current_user_obj()
    if not user:
        return redirect(url_for('index'))

    group_id = request.form.get('group_id', type=int)
    text = request.form.get('text', '').strip()
    file = request.files.get('attachment')

    if not group_id:
        return redirect(url_for('chat'))

    group = ChatGroup.query.get_or_404(group_id)

    user_role = get_user_role(user)
    if user_role != 'LEVEL3':
        is_member = ChatGroupMember.query.filter_by(group_id=group.id, user_id=user.id).first()
        if not is_member:
            return redirect(url_for('chat'))

    if not text and (not file or not file.filename):
        return redirect(url_for('chat', group_id=group.id))

    msg = ChatMessage(group_id=group.id, sender_id=user.id, text=text or '')
    db.session.add(msg)
    db.session.commit()

    if file and file.filename and allowed_chat_file(file.filename):
        safe_name = secure_filename(file.filename)
        fname = f"{msg.id}_{uuid.uuid4().hex}_{safe_name}"
        path = os.path.join(CHAT_ATTACH_FOLDER, fname)
        file.save(path)

        attachment = ChatAttachment(
            message_id=msg.id,
            filename=fname,
            original_name=file.filename,
            content_type=file.mimetype or ''
        )
        db.session.add(attachment)
        db.session.commit()

    return redirect(url_for('chat', group_id=group.id))


@app.route('/chat/groups/create', methods=['POST'])
def chat_create_group():
    user = current_user_obj()
    if not user:
        return redirect(url_for('index'))

    if get_user_role(user) != 'LEVEL3':
        return redirect(url_for('chat'))

    name = request.form.get('name', '').strip()
    if not name:
        return redirect(url_for('chat'))

    group = ChatGroup(name=name, created_by_id=user.id)
    db.session.add(group)
    db.session.commit()

    member = ChatGroupMember(group_id=group.id, user_id=user.id)
    db.session.add(member)
    db.session.commit()

    return redirect(url_for('chat', group_id=group.id))


@app.route('/chat/groups/<int:group_id>/add-member', methods=['POST'])
def chat_add_member(group_id):
    user = current_user_obj()
    if not user:
        return redirect(url_for('index'))

    if get_user_role(user) != 'LEVEL3':
        return redirect(url_for('chat'))

    group = ChatGroup.query.get_or_404(group_id)
    user_id = request.form.get('user_id', type=int)
    if not user_id:
        return redirect(url_for('chat', group_id=group.id))

    existing = ChatGroupMember.query.filter_by(group_id=group.id, user_id=user_id).first()
    if not existing:
        db.session.add(ChatGroupMember(group_id=group.id, user_id=user_id))
        db.session.commit()

    return redirect(url_for('chat', group_id=group.id))


# ---------- START ----------

ensure_schema()
fix_admin_flags()
seed_notes()

if __name__ == '__main__':
    app.run(debug=True)