import numpy as np
import json
from supabase import create_client, Client

SUPABASE_URL = 'https://nkrgasdklmzemrfqxnqa.supabase.co'
SUPABASE_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im5rcmdhc2RrbG16ZW1yZnF4bnFhIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc0Njk2MTUzOSwiZXhwIjoyMDYyNTM3NTM5fQ.PCVLWxaZ2wW0yA2g72K3M8ztZBo7Ua-flT8mKrZzlzE'
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


# Fungsi keanggotaan fuzzy Mamdani
def fuzzify_mamdani(nilai):
    return {
        'rendah': max(0, min(1, (5 - nilai) / 5)),
        'sedang': max(0, 1 - abs(nilai - 5) / 2.5),
        'tinggi': max(0, min(1, (nilai - 5) / 5))
    }

def defuzzifikasi_mamdani(fuzzy_values):
    bobot = {'rendah': 30, 'sedang': 60, 'tinggi': 90}
    total = sum(fuzzy_values[level] * bobot[level] for level in fuzzy_values)
    total_keanggotaan = sum(fuzzy_values.values())
    return total / total_keanggotaan if total_keanggotaan != 0 else 0

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

