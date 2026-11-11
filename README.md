# Travekorea Autopost (Meta API: Instagram, Facebook Page, Threads)

Sistem ini memposting bank konten Travekorea secara otomatis lewat API resmi Meta, tanpa Metricool.

**Cara kerja**
- `content/posts.json` berisi semua post (jam KST, format, file media, caption).
- `media/` berisi poster PNG dan video MP4. File ini disajikan publik lewat GitHub Pages, karena Instagram dan Threads hanya mau mengambil media dari URL publik.
- GitHub Actions menjalankan `scripts/publish.py` setiap 15 menit. Post yang sudah waktunya langsung dipublikasikan ke IG, FB, dan Threads.
- Setiap post yang berhasil dicatat di `state/published.json`, jadi tidak akan pernah diposting dua kali. Run juga dikunci supaya tidak jalan bersamaan.
- Post yang terlambat lebih dari 90 menit (misalnya karena GitHub sedang gangguan) ditandai `missed` dan dilewati. Tujuannya agar tidak ada post yang tayang di jam aneh.
- TikTok tidak bisa lewat Meta API, jadi tetap pakai Metricool atau diposting manual.

**Format yang didukung**

| format | Instagram | Facebook Page | Threads |
|---|---|---|---|
| feed (1 gambar) | ✓ | ✓ | ✓ |
| carousel (2–10) | ✓ | ✓ (multi-foto) | ✓ |
| reels (MP4) | ✓ Reels | ✓ video | ✓ video |
| story | ✓ | ✓ (gambar saja) | dilewati |

Stiker interaktif IG Story (polling, kuis, link) **tidak bisa** ditambahkan lewat API. Story yang butuh stiker sebaiknya diposting manual.

---

## Setup satu kali (sekitar 30–45 menit)

### A. Syarat akun
1. Instagram @travekorea harus berupa akun **Business** (bukan Creator) dan terhubung ke Facebook Page Travekorea.
2. Kakak harus menjadi admin Facebook Page tersebut.

### B. Buat Meta App
1. Buka https://developers.facebook.com/apps → **Create App**.
2. Pilih use case **"Manage everything on your Page"**, lalu tambahkan juga **"Manage messaging & content on Instagram"** dan **"Access the Threads API"**.
3. Tipe app: **Business**. Hubungkan ke Business Portfolio Travekorea jika ada.
4. App cukup dibiarkan dalam mode **Development**. App Review tidak diperlukan, karena yang memposting adalah pemilik akun sendiri.

### C. Token Facebook Page dan Instagram
1. Buka **Graph API Explorer** (https://developers.facebook.com/tools/explorer), lalu pilih app tadi.
2. Klik **Get User Access Token** dan centang izin berikut: `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`, `instagram_basic`, `instagram_content_publish`, `business_management`.
3. Tukar token itu menjadi token jangka panjang di **Access Token Debugger** → **Extend Access Token**.
4. Di Explorer, jalankan `me/accounts` dengan token panjang tadi. Salin `access_token` dan `id` milik Page Travekorea. Token Page ini **tidak kedaluwarsa**.
   - `access_token` → secret **META_PAGE_TOKEN**
   - `id` → variable **META_PAGE_ID**
5. Jalankan `<PAGE_ID>?fields=instagram_business_account`. Nilai `id` di dalamnya → variable **META_IG_USER_ID**.

### D. Token Threads
1. Di app yang sama, buka **Use cases → Threads API → Settings**. Tambahkan akun Threads @travekorea sebagai **Threads Tester**, lalu terima undangannya di Threads (Settings → Account → Website permissions → Invites).
2. Buka **User Token Generator** di halaman Threads API, lalu generate token dengan izin `threads_basic` dan `threads_content_publish`.
3. Tukar menjadi token 60 hari: `https://graph.threads.net/access_token?grant_type=th_exchange_token&client_secret=<APP_SECRET>&access_token=<TOKEN>` → secret **THREADS_TOKEN**.
4. Jalankan `https://graph.threads.net/v1.0/me?fields=id&access_token=<TOKEN>` → variable **THREADS_USER_ID**.
5. Token Threads diperbarui otomatis setiap minggu oleh workflow `refresh-threads-token.yml`. Workflow ini butuh secret **GH_ADMIN_TOKEN**: fine-grained Personal Access Token GitHub dengan izin *Secrets: Read and write* khusus untuk repo ini.

### E. Repo GitHub
1. Buat repo **publik** baru, misalnya `travekorea-autopost`. Repo harus publik supaya GitHub Pages gratis bisa menyajikan media.
2. Settings → Pages → Source: **Deploy from a branch**, branch `main`, folder `/ (root)`.
3. Settings → Secrets and variables → Actions:
   - Secrets: `META_PAGE_TOKEN`, `THREADS_TOKEN`, `GH_ADMIN_TOKEN`
   - Variables: `META_PAGE_ID`, `META_IG_USER_ID`, `THREADS_USER_ID`, `MEDIA_BASE_URL` = `https://<username>.github.io/travekorea-autopost/media`
4. Actions → **Travekorea autopost** → **Run workflow** dengan `dry_run = 1` untuk tes. Log-nya akan menampilkan post apa saja yang akan tayang.
5. **Nyalakan autopost:** tambahkan Variable `AUTOPOST_ENABLED` = `true`. Selama variable ini belum ada, sistem tidak akan memposting apa pun.

**Jangan pernah** menaruh token di file, chat, atau commit. Token hanya boleh disimpan di GitHub Secrets.

---

## Operasional
- **Menghentikan semua posting:** ubah Variable `AUTOPOST_ENABLED` menjadi `false`, atau Actions → Travekorea autopost → ⋯ → **Disable workflow**.
- **Membatalkan satu post:** tambahkan `"skip": true` di post tersebut dalam `posts.json`.
- **Cek sebelum upload bank konten baru:** `python scripts/validate.py`
- **Melihat yang sudah tayang atau gagal:** buka `state/published.json`. Isinya status `ok`, `error` (akan dicoba lagi 15 menit kemudian), atau `missed`.
- **Batas Meta:** IG maksimal 50 post API per 24 jam, Threads 250 per 24 jam. Bank konten 2–3 post per hari masih jauh di bawah batas itu.
