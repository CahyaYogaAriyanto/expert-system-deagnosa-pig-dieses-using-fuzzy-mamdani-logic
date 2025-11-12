from io import BytesIO
import locale
from flask import Flask, render_template, request,flash,session,redirect,url_for,Response,jsonify
import requests
import os
from fuzzy_logic import proses_logika_fuzzy,ambil_gejala_dari_db,buat_basis_pengetahuan
import json
from supabase import create_client, Client
from werkzeug.utils import secure_filename
from flask_socketio import SocketIO, emit, join_room 
import uuid
from datetime import datetime


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

socketio = SocketIO(app, cors_allowed_origins="*")

@app.route('/')
def home():
    return render_template('home.html')


@app.route('/login')
def data():
    return render_template('login.html')

@app.route('/prediksi')
def prediksi():
    if 'user' not in session:
        flash('Silakan login terlebih dahulu untuk mengakses fitur ini.', 'login_required')
        return redirect(url_for('not_login'))
    
    response = supabase.table("gejala").select("*").execute()
    sorted_gejala = sorted(response.data, key=lambda x: x['kode_gejala'])
    return render_template('prediksi.html', rules=sorted_gejala)
    # return redirect(url_for('not_login'))

def format_tanggal_indonesia(tanggal_str):
    if not tanggal_str:  # kalau None atau kosong
        return "Tanggal tidak tersedia"

    hari_mapping = {
        "Monday": "Senin", "Tuesday": "Selasa", "Wednesday": "Rabu",
        "Thursday": "Kamis", "Friday": "Jumat", "Saturday": "Sabtu", "Sunday": "Minggu"
    }
    bulan_mapping = {
        "January": "Januari", "February": "Februari", "March": "Maret", "April": "April",
        "May": "Mei", "June": "Juni", "July": "Juli", "August": "Agustus",
        "September": "September", "October": "Oktober", "November": "November", "December": "Desember"
    }

    # cek apakah value sudah berupa datetime (bukan string)
    if isinstance(tanggal_str, datetime):
        dt = tanggal_str
    else:
        try:
            dt = datetime.strptime(tanggal_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            try:
                dt = datetime.strptime(tanggal_str, "%Y-%m-%d")  # fallback kalau format beda
            except Exception:
                return str(tanggal_str)  # kalau gagal total, tampilkan apa adanya

    hari = hari_mapping[dt.strftime("%A")]
    tanggal = dt.strftime("%d")
    bulan = bulan_mapping[dt.strftime("%B")]
    tahun = dt.strftime("%Y")

    return f"{hari}, {tanggal} {bulan} {tahun}"


@app.route('/not_login')
def not_login():
    return render_template('login_cek.html')

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
    print(hasil_diagnosa)
    id_user = session.get('id_user')
    nama = session.get('nama')
    hasil_tertinggi = {}
    if hasil_diagnosa:
        # Ambil maksimal 3 penyakit dengan skor tertinggi
        penyakit_teratas = sorted(hasil_diagnosa.items(), key=lambda item: item[1], reverse=True)[:3]

        # Hitung total skor mentah
        total_skor = sum([item[1] for item in penyakit_teratas])

        hasil_tertinggi_list = []
        for kode_penyakit, skor in penyakit_teratas:
            # Normalisasi skor jadi persentase
            skor_normalisasi = (skor / total_skor) * 100 if total_skor > 0 else 0

            # Ambil informasi penyakit dari Supabase
            response = supabase.table("penyakit").select("*").eq("kode_penyakit", kode_penyakit).execute()
            if response.data:
                data = response.data[0]
                hasil = {
                    "kode": kode_penyakit,
                    "skor": skor_normalisasi,
                    "nama": data.get("nama_penyakit", "Tidak ditemukan"),
                    "definisi": data.get("definisi", "Tidak ada definisi tersedia."),
                    "rekomendasi": data.get("rekomendasi_penanganan", "Tidak ada rekomendasi.")
                }
            else:
                hasil = {
                    "kode": kode_penyakit,
                    "skor": skor_normalisasi,
                    "nama": "Tidak ditemukan",
                    "definisi": "Tidak ada definisi tersedia.",
                    "rekomendasi": "Tidak ada rekomendasi."
                }
            hasil_tertinggi_list.append(hasil)
        # Simpan ke database hanya penyakit tertinggi (index 0)
        penyakit_utama = hasil_tertinggi_list[0]
        tanggal = datetime.now().strftime("%A, %d %B %Y")
        supabase.table("hasil_diagnosa").insert({
            'id_user': id_user,
            "gejala": ",".join(gejala_aktif),
            "kode_penyakit": penyakit_utama["kode"],
            "nama_penyakit": penyakit_utama["nama"],
            "skor": round(penyakit_utama["skor"], 2),
            "rekomendasi": penyakit_utama["rekomendasi"],
            "nama": nama,
            "tanggal": tanggal,
        }).execute()
    return render_template('hasil.html', hasil=hasil_tertinggi_list, selected=gejala_aktif)

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
@app.route('/akun_pakar', methods=['GET'])
def akun_pakar():
    users = get_all_users()
    pakar_list = supabase.table("pakar").select("*").execute().data
    return render_template('akun_pakar.html', users=users,
                           pakar_list=pakar_list,
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

@app.route('/pakar_add', methods=['POST','GET'])
def pakar_add():
    nama = request.form['nama']
    email = request.form['email']
    password = request.form['password']
    no_tlp = request.form['no_tlp']
    link_maps = request.form['maps']
    # Cek apakah email atau nama sudah ada
    existing = supabase.table("pakar").select("*").or_(f"email.eq.{email},nama.eq.{nama}").execute()
    if existing.data:
        flash("Email atau nama sudah digunakan.", "admin_danger")
        return redirect(url_for("akun_pakar"))
    try:
        user = supabase.auth.sign_up({"email": email, "password": password})
        uid = user.user.id

        data_pakar= {
            "id": uid,
            "nama": nama,
            "email": email,
            "password": password,
            "no_tlp": no_tlp,
            "maps_url": link_maps

        }
        supabase.table("pakar").insert(data_pakar).execute()
        flash('Akun berhasil ditambahkan!', 'admin_success')
    except Exception as e:
        flash('Gagal menambahkan akun: ' + str(e), 'admin_danger')

    return redirect(url_for('akun_pakar'))

# Edit akun pakar
@app.route('/pakar_edit/<id>', methods=['POST'])
def pakar_edit(id):
    nama = request.form['nama']
    email = request.form['email']
    supabase.table("pakar").update({"nama": nama, "email": email}).eq("id", id).execute()
    flash('Akun berhasil diperbarui!', 'admin_success')
    return redirect(url_for('akun_pakar'))

# Hapus akun pakar
@app.route('/pakar_delete/<id>', methods=['POST'])
def pakar_delete(id):
    supabase.table("pakar").delete().eq("id", id).execute()
    flash('Akun berhasil dihapus!', 'admin_success')
    return redirect(url_for('akun_pakar'))

penyakit_list = supabase.table("penyakit").select("*").execute().data
gejala_list = supabase.table("gejala").select("*").execute().data
@app.route('/data_gejala')
def data_gejala():
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

response_hasil = supabase.table("hasil_diagnosa").select("*").order("id", desc=True).execute()
@app.route('/riwayat_diagnosa')
def riwayat_diagnosa():
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


@app.route('/login_user',methods=['POST','GET'])
def login_user():
    return render_template("login_user.html")

@app.route('/login_cek', methods=['POST', 'GET'])
def login_cek():
    email = request.form.get('email')
    password = request.form.get('password')

    # Ambil user berdasarkan email dan password
    result = supabase.table('pengguna').select('*').eq('email', email).eq('password', password).execute()

    if result.data:
        user = result.data[0]
        if user['password'] == password:
            # Simpan data ke dalam session
            session['user'] = user['email']
            session['nama'] = user.get('nama')
            session['id_user'] = user.get('id_user')
            flash('Login berhasil!', 'user_success')
            return redirect(url_for('home'))
        else:
            flash("Password salah.", "user_danger")
            return redirect(url_for('login_user'))
    else:
        flash("Email tidak ditemukan.", "user_danger")
        return redirect(url_for('login_user'))

@app.route('/daftar_user')
def daftar_user():
    return render_template("daftar_user.html")

@app.route('/daftar_cek', methods=['POST'])
def daftar_cek():
    nama = request.form['username']
    email = request.form['email']
    password = request.form['password']

    # Cek apakah sudah ada
    existing = supabase.table('pengguna').select('*').eq('email', email).execute()

    if existing.data:
        flash("Email sudah terdaftar.")
        return redirect(url_for('daftar_user'))
    id_user = str(uuid.uuid4())
    # Simpan ke Supabase
    supabase.table('pengguna').insert({
        'id_user': id_user,
        'nama': nama,
        'email': email,
        'password': password
    }).execute()

    flash("Pendaftaran berhasil. Silakan login.","user_success")
    return redirect(url_for('login_user'))

@app.route('/login_pakar',methods=['POST','GET'])
def login_pakar():
    return render_template("login_pakar.html")

@app.route('/pakar_cek', methods=['POST', 'GET'])
def pakar_cek():
    email = request.form.get('email')
    password = request.form.get('password')
    # Ambil user berdasarkan email dan password
    result = supabase.table('pakar').select('*').eq('email', email).eq('password', password).execute()

    if result.data:
        user = result.data[0]
        if user['password'] == password:
            flash('Login berhasil!', 'pakar_success')
            session['pakar_nama'] = user['nama']
            session['pakar_id'] = user['id']
            session['pakar_email'] = user['email']
            print(session['pakar_id'])
            return redirect(url_for('lc_pakar'))
        else:
            flash("Password salah.", "pakar_danger")
            return redirect(url_for('login_pakar'))
    else:
        flash("Email tidak ditemukan.", "pakar_danger")
        return redirect(url_for('login_pakar'))

@app.route('/lc_user')
def lc_user():
    if 'user' not in session:
        flash('Silakan login terlebih dahulu untuk mengakses fitur ini.', 'login_required')
        return redirect(url_for('not_login'))
    return render_template("lc_user.html",
                           username=session['nama'])

@app.route('/lc_pakar')
def lc_pakar():
    chat = supabase.table("chat_messages").select("id, sender, receiver").execute()
    data = chat.data
    # Hitung total chat
    total_chat = len(data)
    # total user
    senders = set([c['sender'] for c in data if c.get('sender')])
    receivers = set([c['receiver'] for c in data if c.get('receiver')])
    total_users = len(senders.union(receivers))
    return render_template("lc_pakar.html",
                           total_chat =total_chat,
                           total_users= total_users,
                           email = session['pakar_email'],
                           username=session["pakar_nama"])

@socketio.on('join')
def on_join(data):
    username = data['username']
    join_room(username)   # setiap user atau pakar join ke room namanya sendiri
    print(f"[JOIN] {username} masuk ke room: {username}")


@socketio.on('user_message')
def handle_user_message(data):
    sender = data.get('username')
    receiver = data.get('receiver')
    message = data.get('message')

    if not sender or not receiver or not message:
        print("[ERROR] Data tidak lengkap:", data)
        return

    # kirim ke pakar yang dipilih
    emit('user_receive', {
        'sender': sender,
        'message': message
    }, room=receiver)

    # simpan pesan
    simpan_pesan(sender, receiver, message)

@socketio.on('pakar_reply')
def handle_pakar_reply(data):
    sender = data.get('username')   # nama pakar
    receiver = data.get('receiver') # nama user
    message = data.get('message')

    emit('user_receive', {
        'sender': sender,
        'message': message
    }, room=receiver)

    simpan_pesan(sender, receiver, message)

def simpan_pesan(sender, receiver, message):
    url = f"{SUPABASE_URL}/rest/v1/chat_messages"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal"
    }
    data = {
        "sender": sender,
        "receiver": receiver,
        "message": message
    }
    response = requests.post(url, json=data, headers=headers)
    print("Supabase:", response.status_code, response.text)

@app.route('/chat_history')
def chat_history():
    pakar = request.args.get("pakar")
    user = request.args.get("user")

    url = f"{SUPABASE_URL}/rest/v1/chat_messages?select=*&or=(and(sender.eq.{user},receiver.eq.{pakar}),and(sender.eq.{pakar},receiver.eq.{user}))&order=id.asc"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}"
    }
    response = requests.get(url, headers=headers)
    return jsonify(response.json())

@socketio.on("send_message")
def handle_message(data):
    sender = data["sender"]
    receiver = data["receiver"]
    message = data["message"]

    key = tuple(sorted([sender, receiver]))
    if key not in chat_history:
        chat_history[key] = []
    chat_history[key].append({
        "sender": sender,
        "message": message,
        "timestamp": datetime.now().isoformat()
    })

    emit("receive_message", data, broadcast=True)


@app.route('/pakar_list')
def pakar_list():
    response = supabase.table("pakar").select("id, nama").execute()
    pakars = response.data
    return jsonify(pakars)

@app.route("/user_list")
def user_list():
    response = supabase.table("pengguna").select("id_user, nama").execute()
    pakars = response.data
    return jsonify(pakars)

@app.route("/chat_stats")
def chat_stats():
    response = supabase.table("chat_messages").select("receiver").execute()
    data = response.data

    # Hitung jumlah chat per receiver
    counts = {}
    for d in data:
        receiver = d["receiver"]
        counts[receiver] = counts.get(receiver, 0) + 1

    return jsonify(counts)


@app.route('/dashboard_stats')
def dashboard_stats():
    try:
        # Ambil semua chat
        chat = supabase.table("chat_messages").select("id, sender, receiver").execute()
        data = chat.data

        # Hitung total chat
        total_chat = len(data)

        # Hitung total user unik
        senders = set([c['sender'] for c in data if c.get('sender')])
        receivers = set([c['receiver'] for c in data if c.get('receiver')])
        total_users = len(senders.union(receivers))

        # Hitung total pakar (contoh: yang punya nama "admin")
        total_pakar = len([u for u in receivers if u.lower() == "admin"])

        # Hitung jumlah chat per receiver
        chat_by_receiver = {}
        for c in data:
            r = c.get("receiver")
            if r:
                chat_by_receiver[r] = chat_by_receiver.get(r, 0) + 1

        # Ubah ke format list untuk frontend
        chat_receiver_stats = [{"receiver": r, "jumlah": j} for r, j in chat_by_receiver.items()]

        return jsonify({
            "total_users": total_users,
            "total_pakar": total_pakar,
            "total_chat": total_chat,
            "chat_receiver_stats": chat_receiver_stats
        })
    except Exception as e:
        return jsonify({"error": str(e)})
    
@app.route("/riwayat_user")
def riwayat_user():
    if 'id_user' not in session:
        return redirect('/login') 
    id_user = session['id_user']
    response = supabase.table("hasil_diagnosa").select("*").eq("id_user", id_user).execute()
    hasil = response.data

    return render_template("riwayat.html", hasil=hasil)

@app.route('/logout', methods=['GET','POST'])
def logout():
    session.clear() 
    return redirect(url_for('home')) 

@app.context_processor
def inject_request():
    return dict(request=request)

@app.route('/dashboard_user')
def dashboard():

    username = session.get("nama", "Guest User")
    user_id= session.get('id_user')
    result = supabase.table("hasil_diagnosa").select("id").eq("id_user", user_id).execute()
    result_chat = supabase.table("chat_messages").select("id").eq("sender", username).execute()
    jumlah_chat = len(result_chat.data) if result_chat.data else 0
    # Hitung jumlah diagnosa
    jumlah_diagnosa = len(result.data) if result.data else 0
    email = supabase.table("pengguna").select("email").eq("id_user", user_id).execute()
    email_data = email.data[0]["email"] if email.data else "Tidak ada email"

    # riwayat
    response = (
    supabase.table("hasil_diagnosa")
    .select("*")
    .eq("id_user", user_id)
    .order("id", desc=True)
    .limit(5)
    .execute()
    )
    riwayat = response.data
    response_riwayat = supabase.table("hasil_diagnosa").select("*").eq("id_user", user_id).execute()
    riwayat_data= response_riwayat.data
    

    for item in riwayat:
        item["tanggal"] = format_tanggal_indonesia(item["tanggal"])
        item["gejala"] = item.get("gejala", "")
        item["rekomendasi"] = item.get("rekomendasi", "")  


    # statistik
    result_statistik = supabase.table("hasil_diagnosa").select("nama_penyakit").eq("id_user", user_id).execute()
    statistik_data = result_statistik.data

    # Hitung jumlah tiap penyakit
    statistik = {}
    for row in statistik_data:
        penyakit = row["nama_penyakit"]
        statistik[penyakit] = statistik.get(penyakit, 0) + 1

    # Hitung total untuk persentase
    total = sum(statistik.values())
    statistik_persen = {p: round((jumlah/total)*100, 2) for p, jumlah in statistik.items()} 
    pakar_response = supabase.table('pakar').select('*').execute()
    data_pakar = pakar_response.data
    maps_url = 'https://www.google.com/maps/embed?pb=!1m18!1m12!1m3!1d65504.64557968693!2d110.40142645225669!3d-7.753270961649416!2m3!1f0!2f0!3f0!3m2!1i1024!2i768!4f13.1!3m3!1m2!1s0x2e7a58f6765d4a33%3A0x39d891d2e8da95a9!2sJogja%20City%20Mall!5e0!3m2!1sen!2sid!4v1760205983482!5m2!1sen!2sid" width="600" height="450" style="border:0;" allowfullscreen="" loading="lazy" referrerpolicy="no-referrer-when-downgrade'
    return render_template('dashUser/ds_user.html',
                           data_pakar = data_pakar,
                           maps_url=maps_url,
                           statistik=statistik_persen,
                            username = username,
                            email=email_data, 
                            riwayat = riwayat,
                            jumlah_diagnosa =jumlah_diagnosa ,
                            riwayat_data=riwayat_data,
                            jumlah_chat = jumlah_chat,
                            )


if __name__ == '__main__':
    socketio.run(app, debug=True)