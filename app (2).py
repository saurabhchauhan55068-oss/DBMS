from flask import Flask, request, jsonify, session, send_from_directory
from flask_cors import CORS
import mysql.connector
from mysql.connector import Error
import hashlib
from datetime import datetime, date
import json
import os

app = Flask(__name__, static_folder='.', static_url_path='')
app.secret_key = 'healthcare_secret_key_2024'
CORS(app, supports_credentials=True)

# ─── DB CONFIG ────────────────────────────────────────────────
DB_CONFIG = {
    'host': 'localhost',
    'database': 'healthcare_db',
    'user': 'root',         # Change to your MySQL username
    'password': 'root'      # Change to your MySQL password
}

def get_db():
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        return conn
    except Error as e:
        print(f"DB Error: {e}")
        return None

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def serialize(obj):
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")

# ─── SERVE FRONTEND ───────────────────────────────────────────

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/<path:filename>')
def static_files(filename):
    return send_from_directory('.', filename)

# ─── AUTH ROUTES ──────────────────────────────────────────────

@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    conn = get_db()
    if not conn:
        return jsonify({'error': 'DB connection failed'}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id FROM users WHERE email=%s", (data['email'],))
        if cursor.fetchone():
            return jsonify({'error': 'Email already registered'}), 400

        hashed = hash_password(data['password'])
        cursor.execute(
            "INSERT INTO users (name, email, password, role, phone) VALUES (%s,%s,%s,%s,%s)",
            (data['name'], data['email'], hashed, data.get('role', 'patient'), data.get('phone', ''))
        )
        user_id = cursor.lastrowid

        if data.get('role') == 'doctor':
            cursor.execute(
                "INSERT INTO doctors (user_id, specialization, qualification, experience_years) VALUES (%s,%s,%s,%s)",
                (user_id, data.get('specialization',''), data.get('qualification',''), data.get('experience', 0))
            )
        else:
            cursor.execute(
                "INSERT INTO patients (user_id, date_of_birth, gender, blood_group) VALUES (%s,%s,%s,%s)",
                (user_id, data.get('dob') or None, data.get('gender', 'Other'), data.get('blood_group', ''))
            )

        conn.commit()
        return jsonify({'message': 'Registered successfully', 'user_id': user_id}), 201
    except Error as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close(); conn.close()


@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    conn = get_db()
    if not conn:
        return jsonify({'error': 'DB connection failed'}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        hashed = hash_password(data['password'])
        cursor.execute("SELECT * FROM users WHERE email=%s AND password=%s", (data['email'], hashed))
        user = cursor.fetchone()
        if not user:
            return jsonify({'error': 'Invalid email or password'}), 401
        session['user_id'] = user['id']
        session['role'] = user['role']
        return jsonify({
            'message': 'Login successful',
            'user': {'id': user['id'], 'name': user['name'], 'email': user['email'], 'role': user['role']}
        })
    finally:
        cursor.close(); conn.close()


@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'message': 'Logged out'})


# ─── DOCTORS ─────────────────────────────────────────────────

@app.route('/api/doctors', methods=['GET'])
def get_doctors():
    conn = get_db()
    if not conn:
        return jsonify({'error': 'DB error'}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT u.id, u.name, u.email, u.phone, d.specialization, d.qualification, d.experience_years
            FROM users u JOIN doctors d ON u.id = d.user_id
            WHERE u.role = 'doctor'
        """)
        return jsonify(cursor.fetchall())
    finally:
        cursor.close(); conn.close()


# ─── APPOINTMENTS ─────────────────────────────────────────────

@app.route('/api/appointments', methods=['POST'])
def book_appointment():
    data = request.json
    conn = get_db()
    if not conn:
        return jsonify({'error': 'DB error'}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "INSERT INTO appointments (patient_id, doctor_id, appointment_date, appointment_time, reason) VALUES (%s,%s,%s,%s,%s)",
            (data['patient_id'], data['doctor_id'], data['date'], data['time'], data.get('reason', ''))
        )
        conn.commit()
        return jsonify({'message': 'Appointment booked!', 'id': cursor.lastrowid}), 201
    except Error as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close(); conn.close()


@app.route('/api/appointments/patient/<int:patient_id>', methods=['GET'])
def get_patient_appointments(patient_id):
    conn = get_db()
    if not conn:
        return jsonify({'error': 'DB error'}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT a.*, u.name as doctor_name, d.specialization
            FROM appointments a
            JOIN users u ON a.doctor_id = u.id
            JOIN doctors d ON d.user_id = u.id
            WHERE a.patient_id = %s
            ORDER BY a.appointment_date DESC, a.appointment_time DESC
        """, (patient_id,))
        rows = cursor.fetchall()
        return jsonify(json.loads(json.dumps(rows, default=serialize)))
    finally:
        cursor.close(); conn.close()


@app.route('/api/appointments/doctor/<int:doctor_id>', methods=['GET'])
def get_doctor_appointments(doctor_id):
    conn = get_db()
    if not conn:
        return jsonify({'error': 'DB error'}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT a.*, u.name as patient_name, u.phone as patient_phone
            FROM appointments a
            JOIN users u ON a.patient_id = u.id
            WHERE a.doctor_id = %s
            ORDER BY a.appointment_date ASC, a.appointment_time ASC
        """, (doctor_id,))
        rows = cursor.fetchall()
        return jsonify(json.loads(json.dumps(rows, default=serialize)))
    finally:
        cursor.close(); conn.close()


@app.route('/api/appointments/<int:appt_id>/status', methods=['PUT'])
def update_appointment_status(appt_id):
    data = request.json
    conn = get_db()
    if not conn:
        return jsonify({'error': 'DB error'}), 500
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE appointments SET status=%s WHERE id=%s", (data['status'], appt_id))
        conn.commit()
        return jsonify({'message': 'Status updated'})
    finally:
        cursor.close(); conn.close()


# ─── MEDICAL RECORDS ─────────────────────────────────────────

@app.route('/api/records', methods=['POST'])
def add_record():
    data = request.json
    conn = get_db()
    if not conn:
        return jsonify({'error': 'DB error'}), 500
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO medical_records (patient_id, doctor_id, appointment_id, diagnosis, prescription, test_results, notes, record_date) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (data['patient_id'], data['doctor_id'], data.get('appointment_id'),
             data.get('diagnosis',''), data.get('prescription',''),
             data.get('test_results',''), data.get('notes',''), data.get('record_date', date.today()))
        )
        conn.commit()
        return jsonify({'message': 'Record added', 'id': cursor.lastrowid}), 201
    except Error as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close(); conn.close()


@app.route('/api/records/patient/<int:patient_id>', methods=['GET'])
def get_patient_records(patient_id):
    conn = get_db()
    if not conn:
        return jsonify({'error': 'DB error'}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT mr.*, u.name as doctor_name, d.specialization
            FROM medical_records mr
            JOIN users u ON mr.doctor_id = u.id
            JOIN doctors d ON d.user_id = u.id
            WHERE mr.patient_id = %s
            ORDER BY mr.record_date DESC
        """, (patient_id,))
        rows = cursor.fetchall()
        return jsonify(json.loads(json.dumps(rows, default=serialize)))
    finally:
        cursor.close(); conn.close()


# ─── DASHBOARD STATS ──────────────────────────────────────────

@app.route('/api/stats', methods=['GET'])
def get_stats():
    conn = get_db()
    if not conn:
        return jsonify({'error': 'DB error'}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT COUNT(*) as total FROM users WHERE role='patient'")
        patients = cursor.fetchone()['total']
        cursor.execute("SELECT COUNT(*) as total FROM users WHERE role='doctor'")
        doctors = cursor.fetchone()['total']
        cursor.execute("SELECT COUNT(*) as total FROM appointments")
        appointments = cursor.fetchone()['total']
        cursor.execute("SELECT COUNT(*) as total FROM appointments WHERE status='pending'")
        pending = cursor.fetchone()['total']
        cursor.execute("SELECT COUNT(*) as total FROM medical_records")
        records = cursor.fetchone()['total']
        return jsonify({'patients': patients, 'doctors': doctors, 'appointments': appointments, 'pending': pending, 'records': records})
    finally:
        cursor.close(); conn.close()


# ─── PATIENTS LIST ────────────────────────────────────────────

@app.route('/api/patients', methods=['GET'])
def get_patients():
    conn = get_db()
    if not conn:
        return jsonify({'error': 'DB error'}), 500
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT u.id, u.name, u.email, u.phone, u.created_at,
                   p.date_of_birth, p.gender, p.blood_group
            FROM users u
            LEFT JOIN patients p ON u.id = p.user_id
            WHERE u.role = 'patient'
            ORDER BY u.created_at DESC
        """)
        rows = cursor.fetchall()
        return jsonify(json.loads(json.dumps(rows, default=serialize)))
    finally:
        cursor.close(); conn.close()


if __name__ == '__main__':
    print("\n✅ MediCare is running!")
    print("👉 Open your browser and go to: http://127.0.0.1:5000\n")
    app.run(debug=True, port=5000)
