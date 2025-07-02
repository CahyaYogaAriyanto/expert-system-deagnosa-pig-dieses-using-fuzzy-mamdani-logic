import numpy as np
import json
from supabase import create_client, Client

SUPABASE_URL = 'https://nkrgasdklmzemrfqxnqa.supabase.co'
SUPABASE_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im5rcmdhc2RrbG16ZW1yZnF4bnFhIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc0Njk2MTUzOSwiZXhwIjoyMDYyNTM3NTM5fQ.PCVLWxaZ2wW0yA2g72K3M8ztZBo7Ua-flT8mKrZzlzE'
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


# Fungsi keanggotaan fuzzy Mamdani
def fuzzify_mamdani(nilai):
    # --- RENDANG ---
    if nilai <= 5 :
        derajat_rendah = (5 - nilai) / 5
    else:
        derajat_rendah = 0.0
    # --- SEDANG ---
    if 2.5 <= nilai <= 7.5:
        derajat_sedang = 1 - abs(nilai - 5) / 2.5 
    else:
        derajat_sedang = 0.0

    # --- TINGGI ---
    if nilai >= 5:
        derajat_tinggi = (nilai - 5) / 5  
    else:
        derajat_tinggi = 0.0 

    # Pastikan semua nilai dalam rentang 0 sampai 1
    derajat_rendah = max(0.0, min(1.0, derajat_rendah))
    derajat_sedang = max(0.0, min(1.0, derajat_sedang))
    derajat_tinggi = max(0.0, min(1.0, derajat_tinggi))

    # Kembalikan sebagai dictionary
    return {
        'rendah': derajat_rendah,
        'sedang': derajat_sedang,
        'tinggi': derajat_tinggi
    }

def defuzzifikasi_mamdani(fuzzy_values):
    # Domain output dari 0 sampai 100
    z_values = np.linspace(0, 100, 1000)

    # Fungsi keanggotaan berdasarkan nilai fuzzy hasil sebelumnya
    def mu_rendah(z):
        return np.clip((50 - z) / 50, 0, 1) * fuzzy_values['rendah']

    def mu_sedang(z):
        return np.clip(1 - np.abs(z - 50) / 25, 0, 1) * fuzzy_values['sedang']

    def mu_tinggi(z):
        return np.clip((z - 50) / 50, 0, 1) * fuzzy_values['tinggi']

    # Gabungan dari semua nilai fuzzy
    mu_total = np.maximum.reduce([mu_rendah(z_values), mu_sedang(z_values), mu_tinggi(z_values)])

    # Hitung nilai defuzzifikasi menggunakan rumus centroid
    numerator = np.sum(z_values * mu_total)
    denominator = np.sum(mu_total)

    return numerator / denominator if denominator != 0 else 0


def ambil_gejala_dari_db(gejala_aktif):
    response = supabase.table("gejala").select("kode_gejala,nama,bobot,kode_penyakit").in_("kode_gejala", gejala_aktif).execute()
    return response.data if response.data else []

def buat_basis_pengetahuan(gejala_data):
    basis = {}
    for item in gejala_data:
        kode = item['kode_gejala']
        penyakit = item.get('kode_penyakit', [])
        if isinstance(penyakit, str):
            penyakit = [p.strip() for p in penyakit.split(',')]
        basis[kode] = penyakit
    return basis

def proses_logika_fuzzy(gejala_aktif_dan_bobot, basis_pengetahuan):
    penyakit_gejala_map = {}

    for item in gejala_aktif_dan_bobot:
        kode = item['kode_gejala']
        bobot = item['bobot']
        for kode_penyakit in basis_pengetahuan.get(kode, []):
            penyakit_gejala_map.setdefault(kode_penyakit, []).append({'kode_gejala': kode, 'bobot': bobot})

    hasil = {}

    for kode_penyakit, gejala_items in penyakit_gejala_map.items():
        nilai_fuzzy = {'rendah': [], 'sedang': [], 'tinggi': []}
        total_bobot = {'rendah': 0, 'sedang': 0, 'tinggi': 0}

        for item in gejala_items:
            nilai_input = 8
            bobot = float(item['bobot'])
            fz = fuzzify_mamdani(nilai_input)

            for level in ['rendah', 'sedang', 'tinggi']:
                nilai_fuzzy[level].append(fz[level] * bobot)
                total_bobot[level] += bobot
        fuzzy_avg = {
            level: sum(nilai_fuzzy[level]) / total_bobot[level] if total_bobot[level] else 0
            for level in ['rendah', 'sedang', 'tinggi']
        }
        z = defuzzifikasi_mamdani(fuzzy_avg)
        # Penyesuaian berdasarkan jumlah gejala yang cocok
        tingkat_kecocokan = len(gejala_items) / max(len(gejala_aktif_dan_bobot), 1)
        z_akhir = z * tingkat_kecocokan
        hasil[kode_penyakit] = round(z_akhir, 2)

    return dict(sorted(hasil.items(), key=lambda x: x[1], reverse=True))

