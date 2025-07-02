from io import BytesIO
import tempfile
import traceback
from flask import Flask, render_template, request,flash, session, redirect, url_for, Response, jsonify
import sqlite3
import mysql.connector
import requests
from pyngrok import ngrok
import cv2
from PIL import Image
import numpy as np
import os
from fuzzy_logic import proses_logika_fuzzy,ambil_gejala_dari_db,buat_basis_pengetahuan
import json
from supabase import create_client, Client
from werkzeug.utils import secure_filename
import uuid

app = Flask(__name__)
 
SUPABASE_URL = 'https://nkrgasdklmzemrfqxnqa.supabase.co'
SUPABASE_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im5rcmdhc2RrbG16ZW1yZnF4bnFhIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc0Njk2MTUzOSwiZXhwIjoyMDYyNTM3NTM5fQ.PCVLWxaZ2wW0yA2g72K3M8ztZBo7Ua-flT8mKrZzlzE'
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
app.secret_key = 'super-secret-key' 

# Set path untuk folder upload
app.config['UPLOAD_FOLDER'] = os.path.join('static', 'foto_admin')
# Buat folder jika belum ada
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
UPLOAD_FOLDER = 'static/foto_admin'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}


@app.route('/')
def home():
    return render_template('home.html')

@app.route('/login')
def data():
    return render_template('login.html')

@app.route('/prediksi')
def prediksi():
    response = supabase.table("gejala").select("*").execute()
    sorted_gejala = sorted(response.data, key=lambda x: x['kode_gejala'])
    return render_template('prediksi.html', rules=sorted_gejala)

@app.route('/hasil', methods=['POST'])
def hasil():
    gejala_aktif = request.form.getlist('symptoms')
    
    # Ambil data gejala dari Supabase
    gejala_data = ambil_gejala_dari_db(gejala_aktif)

    if not gejala_data:
        return jsonify({"error": "Gejala tidak ditemukan"}), 400

    # Buat basis pengetahuan dari data gejala (menghubungkan gejala ke penyakit)
    basis_pengetahuan = buat_basis_pengetahuan(gejala_data)

    # Gabungkan kode gejala dan bobot untuk proses fuzzy
    gejala_aktif_dan_bobot = [
        {
            'kode_gejala': item['kode_gejala'],
            'bobot': float(item.get('bobot', 1))
        }
        for item in gejala_data
    ]
    # Proses logika fuzzy untuk menghitung skor keyakinan per penyakit
    hasil_diagnosa = proses_logika_fuzzy(gejala_aktif_dan_bobot, basis_pengetahuan)
    nama = request.form.get('nama')
    hasil_tertinggi = {}
    if hasil_diagnosa:
        # Ambil penyakit dengan skor tertinggi
        top_disease = max(hasil_diagnosa, key=hasil_diagnosa.get)
        nilai_tertinggi = hasil_diagnosa[top_disease]

        # Ambil informasi penyakit dari Supabase
        response = supabase.table("penyakit").select("*").eq("kode_penyakit", top_disease).execute()
        if response.data:
            data = response.data[0]
            hasil_tertinggi = {
                "kode": top_disease,
                "skor": nilai_tertinggi,
                "nama": data.get("nama_penyakit", "Tidak ditemukan"),
                "definisi": data.get("definisi", "Tidak ada definisi tersedia."),
                "rekomendasi": data.get("rekomendasi_penanganan", "Tidak ada rekomendasi.")
            }
        else:
            hasil_tertinggi = {
                "kode": top_disease,
                "skor": nilai_tertinggi,
                "nama": "Tidak ditemukan",
                "definisi": "Tidak ada definisi tersedia.",
                "rekomendasi": "Tidak ada rekomendasi."
            }

        # Simpan hasil ke database
        supabase.table("hasil_diagnosa").insert({
            "gejala": ",".join(gejala_aktif),
            "kode_penyakit": top_disease,
            "nama_penyakit": hasil_tertinggi["nama"],
            "skor": nilai_tertinggi,
            "rekomendasi": hasil_tertinggi["rekomendasi"],
            "nama" : nama,
        }).execute()

    return render_template('hasil.html', hasil=hasil_tertinggi, selected=gejala_aktif)


@app.route('/about')
def about():
    return render_template('about.html')


def get_all_users():
    url = f"{SUPABASE_URL}/auth/v1/admin/users"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }

    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        data = response.json()
        return data.get("users", [])
    else:
        print("Gagal mengambil data user:", response.text)
        return []


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        try:
            user = supabase.auth.sign_in_with_password({"email": email, "password": password})
            if user.user is None:
                flash('Login gagal: Email atau password salah.', 'login_danger')
                return redirect(url_for('login'))

            session['user'] = user.user.email

            # Ambil data dari tabel admin berdasarkan email
            response = supabase.table('admin').select('nama, foto').eq('email', email).execute()
            admin_data = response.data[0] if response.data else None

            if admin_data:
                session['nama_admin'] = admin_data['nama']
                session['foto_admin'] = admin_data['foto']
            else:
                flash('Data admin tidak ditemukan.', 'admin_danger')

            flash('Login berhasil!', 'login_success')
            return redirect(url_for('admin'))

        except Exception as e:
            flash('Login gagal: ' + str(e), 'login_danger')
            return redirect(url_for('login'))
    return render_template('login.html')


@app.route('/admin', methods=['GET'])
def admin():
    if 'user' not in session:
        flash('Silakan login terlebih dahulu.', 'login_danger')
        return redirect(url_for('login'))

    users = get_all_users()
    return render_template('admin.html', users=users,
                           nama_admin=session.get('nama_admin'),
                           foto_admin=session.get('foto_admin'))

@app.route('/admin_add', methods=['POST'])
def admin_add():
    if 'user' not in session:
        return redirect(url_for('login'))

    nama = request.form['nama']
    email = request.form['email']
    password = request.form['password']
    foto = request.files['foto']

    # Cek apakah email atau nama sudah ada
    existing = supabase.table("admin").select("*").or_(f"email.eq.{email},nama.eq.{nama}").execute()
    if existing.data:
        flash("Email atau nama sudah digunakan.", "admin_danger")
        return redirect(url_for("admin"))

    filename = secure_filename(nama.lower().replace(" ", "_") + "_" + foto.filename)
    file_bytes = BytesIO(foto.read())

    try:
        supabase.storage.from_('admin-foto').upload(
            path=filename,
            file=file_bytes.getvalue(),
            file_options={"content-type": foto.mimetype}
        )
    except Exception as e:
        flash("Gagal upload foto: " + str(e), "admin_danger")
        return redirect(url_for('admin'))

    foto_url = f"https://{SUPABASE_URL.split('//')[1]}/storage/v1/object/public/admin-foto/{filename}"

    try:
        user = supabase.auth.sign_up({"email": email, "password": password})
        uid = user.user.id

        data_admin = {
            "uid": uid,
            "nama": nama,
            "email": email,
            "password": password,
            "foto": foto_url
        }

        supabase.table("admin").insert(data_admin).execute()
        flash('Akun berhasil ditambahkan!', 'admin_success')
    except Exception as e:
        flash('Gagal menambahkan akun: ' + str(e), 'admin_danger')

    return redirect(url_for('admin'))

@app.route('/edit_user', methods=['POST'])
def edit_user():
    uid = request.form.get('uid')
    new_email = request.form.get('email')
    new_nama = request.form.get('nama')
    new_password = request.form.get('new_password')

    if not new_email:
        flash("Email harus diisi.", "admin_danger")
        return redirect(url_for('admin'))
    existing_email = supabase.table("admin")\
        .select("*")\
        .eq("email", new_email)\
        .neq("uid", uid)\
        .execute()

    if existing_email.data:
        flash("Email sudah digunakan oleh admin lain.", "admin_danger")
        return redirect(url_for('admin'))

    if new_nama:
        existing_nama = supabase.table("admin")\
            .select("*")\
            .eq("nama", new_nama)\
            .neq("uid", uid)\
            .execute()
        if existing_nama.data:
            flash("Nama sudah digunakan oleh admin lain.", "admin_danger")
            return redirect(url_for('admin'))

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }

    try:
        users_response = requests.get(
            f"{SUPABASE_URL}/auth/v1/admin/users",
            headers=headers
        )

        users_data = users_response.json()
        users = users_data.get("users", [])

        email_conflict = False
        for user in users:
            if user['email'] == new_email and user['id'] != uid:
                email_conflict = True
                break

        if email_conflict:
            flash("Email sudah digunakan oleh pengguna lain di Auth.", "admin_danger")
            return redirect(url_for('admin'))

        # Update di Auth
        update_data = {"email": new_email}
        if new_password:
            update_data["password"] = new_password

        response = requests.put(
            f"{SUPABASE_URL}/auth/v1/admin/users/{uid}",
            headers=headers,
            json=update_data
        )
        if response.status_code != 200:
            flash("Gagal memperbarui akun Auth: " + response.text, "admin_danger")
            return redirect(url_for('admin'))

        # Update di tabel admin
        update_admin = {"email": new_email}
        if new_nama:
            update_admin["nama"] = new_nama
        if new_password:
            update_admin["password"] = new_password

        supabase.table("admin").update(update_admin).eq("uid", uid).execute()

        flash("Akun berhasil diperbarui", "admin_success")
    except Exception as e:
        flash("Terjadi kesalahan: " + str(e), "admin_danger")

    return redirect(url_for('admin'))

@app.route('/delete_user', methods=['POST'])
def delete_user():
    uid = request.form.get('uid')
    try:
        user_info = requests.get(
            f"{SUPABASE_URL}/auth/v1/admin/users/{uid}",
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
            }
        )

        if user_info.status_code != 200:
            flash("Gagal mendapatkan info pengguna", "admin_danger")
            return redirect(url_for('admin'))

        user_data = user_info.json()
        email = user_data.get("email")

        # Hapus data admin dari tabel 
        supabase.table("admin").delete().eq("email", email).execute()

        # Hapus akun dari Supabase Auth
        delete_response = requests.delete(
            f"{SUPABASE_URL}/auth/v1/admin/users/{uid}",
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
            }
        )

        if delete_response.status_code == 204:
            flash("Akun berhasil dihapus", "admin_success")
        else:
            flash("Gagal menghapus akun auth: " + delete_response.text, "admin_danger")

    except Exception as e:
        flash("Terjadi kesalahan: " + str(e), "admin_danger")

    return redirect(url_for('admin'))

@app.route('/akun_admin')
def akun_admin():
    users = get_all_users()
    return render_template("akun_admin.html",
                                nama_admin=session.get('nama_admin'),
                                foto_admin=session.get('foto_admin'),
                                users=users)

penyakit_list = supabase.table("penyakit").select("*").execute().data

@app.route('/data_gejala')
def data_gejala():
    gejala_list = supabase.table("gejala").select("*").execute().data
    sorted_gejala = sorted(gejala_list, key=lambda x: x['kode_gejala'])
    last_kode = sorted_gejala[-1]['kode_gejala'] if sorted_gejala else 'G00'
    return render_template("data_gejala.html",
                                gejala_list=sorted_gejala,
                                last_kode=last_kode,
                                nama_admin=session.get('nama_admin'),
                                foto_admin=session.get('foto_admin'))
                                
@app.route('/data_penyakit')
def data_penyakit():
    # sorted_penyakit = sorted(penyakit_list, key=lambda x: x['kode_penyakit'])
    sorted_penyakit = sorted(penyakit_list, key=lambda x: int(x['kode_penyakit'].replace('P', '')))
    return render_template("data_penyakit.html",
                                penyakit_list=sorted_penyakit,
                                nama_admin=session.get('nama_admin'),
                                foto_admin=session.get('foto_admin'))

@app.route('/riwayat_diagnosa')
def riwayat_diagnosa():
    response_hasil = supabase.table("hasil_diagnosa").select("*").order("id", desc=True).execute()
    hasil_list = response_hasil.data if response_hasil.data else []
    return render_template("riwayat_diagnosa.html", 
                           nama_admin=session.get('nama_admin'),
                            foto_admin=session.get('foto_admin'),
                           hasil_list=hasil_list)

@app.route('/tambah_gejala', methods=['POST'])
def tambah_gejala():
    kode_gejala = request.form.getlist('kode_gejala')
    nama = request.form.getlist('nama')
    kode_penyakit = request.form.getlist('kode_penyakit')
    bobot = request.form.getlist('bobot')

    if not (len(kode_gejala) == len(nama) == len(kode_penyakit) == len(bobot)):
        flash("❌ Data tidak lengkap atau tidak sejajar", "danger")
        return redirect(url_for('data_gejala'))

    existing_data = supabase.table("gejala").select("kode_gejala, nama").execute().data
    for i in range(len(kode_gejala)):
        for item in existing_data:
            if item['kode_gejala'].lower() == kode_gejala[i].lower():
                flash(f"❌ Gagal menambahkan Kode gejala '{kode_gejala[i]}' sudah ada.", "danger")
                return redirect(url_for('data_gejala'))
            if item['nama'].lower() == nama[i].lower():
                flash(f"❌ Gagal menambahkan gejala '{nama[i]}' sudah ada.", "danger")
                return redirect(url_for('data_gejala'))
    data_baru = []
    for i in range(len(kode_gejala)):
        data_baru.append({
            "kode_gejala": kode_gejala[i],
            "nama": nama[i],
            "kode_penyakit": kode_penyakit[i],
            "bobot": bobot[i]
        })
    response = supabase.table("gejala").insert(data_baru).execute()

    if response.data:
        flash("✅ Data gejala berhasil ditambahkan.", "success")
    else:
        flash("❌ Gagal menambahkan data gejala.", "danger")

    return redirect(url_for('data_gejala'))

@app.route('/hapus_gejala/<string:kode_gejala>', methods=['POST'])
def hapus_gejala(kode_gejala):
    response = supabase.table("gejala").delete().eq("kode_gejala", kode_gejala).execute()
    if response and response.data:
        print()
        flash("✅ Data gejala berhasil dihapus.", "success")
    else:
        flash("❌ Gagal menghapus data ", "danger")
    gejala_Data = supabase.table("gejala").select("*").execute().data
    sorted_gejala = sorted(gejala_Data, key=lambda x: x['kode_gejala'])
    last_kode = sorted_gejala[-1]['kode_gejala'] if sorted_gejala else 'G00'

    return render_template("data_gejala.html",
                           gejala_list=sorted_gejala,
                           last_kode=last_kode,
                           nama_admin=session.get('nama_admin'),
                           foto_admin=session.get('foto_admin'))

@app.route('/tambah_penyakit', methods=['POST'])
def tambah_penyakit():
    kode = request.form['kode_penyakit'].strip().upper()
    
    nama = request.form['nama_penyakit']
    definisi = request.form['definisi']
    rekomendasi = request.form['rekomendasi_penanganan']

    existing_data = supabase.table("penyakit").select("kode_penyakit, nama_penyakit").execute().data

    for penyakit in existing_data:
        if penyakit['kode_penyakit'].lower() == kode.lower():
            flash('❌ Kode penyakit sudah digunakan.', 'danger')
            return redirect(url_for('data_penyakit'))
        if penyakit['nama_penyakit'].lower() == nama.lower():
            flash('❌ Nama penyakit sudah ada.', 'danger')
            return redirect(url_for('data_penyakit'))

    supabase.table("penyakit").insert([{
        "kode_penyakit": kode,
        "nama_penyakit": nama,
        "definisi": definisi,
        "rekomendasi_penanganan": rekomendasi
    }]).execute()

    flash('✅ Data penyakit berhasil ditambahkan.', 'success')
    penyakit_data = supabase.table("penyakit").select("*").execute().data
    sorted_penyakit = sorted(penyakit_data, key=lambda x: int(x['kode_penyakit'].replace('P', '')))

    return render_template("data_penyakit.html",
                           penyakit_list=sorted_penyakit,
                           nama_admin=session.get('nama_admin'),
                           foto_admin=session.get('foto_admin'))

@app.route('/hapus_penyakit/<string:kode_penyakit>', methods=['POST'])
def hapus_penyakit(kode_penyakit):
    response = supabase.table("penyakit").delete().eq("kode_penyakit", kode_penyakit).execute()
    penyakit_data = supabase.table("penyakit").select("*").execute().data
    flash('✅ Data penyakit berhasil dihapus.', 'success')
    return render_template("data_penyakit.html",
                           penyakit_list=penyakit_data,
                           nama_admin=session.get('nama_admin'),
                           foto_admin=session.get('foto_admin'))

                            
@app.route('/logout', methods=['POST'])
def logout():
    session.clear() 
    return redirect(url_for('home')) 

@app.context_processor
def inject_request():
    return dict(request=request)

# if __name__ == "__main__":
#     # buka port 5000
#     public_url = ngrok.connect(5000)
#     print(" * Ngrok URL:", public_url)
    
#     app.run(port=5000)


if __name__ == "__main__":
    app.run(debug=True)

