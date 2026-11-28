"""
NetNabız Yük Testi Aracı (tools/load_test.py).

Geçici bir konfigürasyon ve veritabanıyla (data/loadtest_tmp_*/loadtest.db)
izole bir uvicorn sunucusu başlatır. httpx ile eşzamanlı iş parçacıklarından istek göndererek
WAL modu açık ve kapalı durumdaki performansı (saniyedeki istek sayısı,
ortalama / medyan / %95 gecikme) ölçer ve doğrular.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time

_BASE_DIR = Path(__file__).resolve().parent.parent
if str(_BASE_DIR) not in sys.path:
    sys.path.insert(0, str(_BASE_DIR))

import httpx

def find_free_port() -> int:
    """Kullanılabilir rastgele bir yerel port bulur."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def run_benchmark_pass(
    total_requests: int = 1000,
    concurrency: int = 20,
    wal_mode: bool = True,
    port: int | None = None,
) -> dict:
    """C iş parçacığıyla tek bir izole sunucu yük testini çalıştırır."""
    if total_requests < 1:
        raise ValueError("total_requests en az 1 olmalı.")
    if concurrency < 1:
        raise ValueError("concurrency en az 1 olmalı.")

    port = port or find_free_port()
    data_dir = _BASE_DIR / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(
        prefix=f"loadtest_tmp_{'wal' if wal_mode else 'nowal'}_", dir=data_dir
    ))

    db_path = temp_dir / "loadtest.db"
    config_path = temp_dir / "config_loadtest.toml"
    server_log_path = temp_dir / "server.log"
    server_process = None

    try:
        # Yalnızca yük testine özel DB'yi gösteren geçici ayar oluştur.
        toml_content = f"""
database_path = "{db_path.as_posix()}"
hash_salt = "load-test-salt-secret"
api_key = "loadtest-api-key"
campus_ip_ranges = []
dev_mode = true
zones = ["Kütüphane 1. kat Okuma salonu", "Mühendislik B Blok 2. kat Derslik koridoru"]

[storage]
backend = "sqlite"
busy_timeout_ms = 10000
wal_mode = {'true' if wal_mode else 'false'}
"""
        config_path.write_text(toml_content.strip(), encoding="utf-8")

        server_env = os.environ.copy()
        server_env["NETNABIZ_CONFIG"] = str(config_path)
        command = [
            sys.executable, "-m", "uvicorn", "backend.main:app",
            "--host", "127.0.0.1", "--port", str(port), "--no-access-log",
        ]
        # Başlatma hatası olsa bile en dıştaki finally geçici klasörü temizler.
        log_file = server_log_path.open("w", encoding="utf-8")
        try:
            server_process = subprocess.Popen(
                command, cwd=str(_BASE_DIR), env=server_env,
                stdout=log_file, stderr=subprocess.STDOUT,
            )
        finally:
            log_file.close()

        base_url = f"http://127.0.0.1:{port}"
        server_ready = False
        for _ in range(50):
            if server_process.poll() is not None:
                break
            try:
                resp = httpx.get(f"{base_url}/health", timeout=0.2)
                if resp.status_code == 200:
                    server_ready = True
                    break
            except Exception:
                time.sleep(0.1)

        if not server_ready:
            log_tail = ""
            if server_log_path.exists():
                log_tail = "\n".join(server_log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-12:])
            raise RuntimeError(
                f"Yük testi sunucusu {port} portunda hazır olamadı. "
                f"Sunucu günlüğü:\n{log_tail or '(boş)'}"
            )

        # Bir httpx.Client oturumunu eşzamanlı C iş parçacığı paylaşır.
        latencies = []
        errors = 0
        headers = {"x-api-key": "loadtest-api-key"}
        limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)

        def send_one(request_id: int, client: httpx.Client) -> tuple[float | None, str | None]:
            payload = {
                "device_hash": f"dev-loadtest-{request_id}",
                "source": "desktop",
                "zone": "Kütüphane 1. kat Okuma salonu",
                "is_simulated": 1,
                "rtt_ms": 22.5,
                "loss_pct": 0.0,
                "down_mbps": 50.0,
                "up_mbps": 10.0,
                "campus_confidence": 1.0,
                "is_verified": 1,
            }
            start = time.perf_counter()
            try:
                response = client.post(f"{base_url}/measurements", json=payload, headers=headers)
                elapsed = (time.perf_counter() - start) * 1000.0
                if response.status_code in (200, 201):
                    return elapsed, None
                return None, f"HTTP {response.status_code}"
            except Exception as error:
                return None, str(error)

        start_time = time.perf_counter()
        with httpx.Client(limits=limits, timeout=15.0) as client:
            with ThreadPoolExecutor(max_workers=concurrency) as executor:
                results = list(executor.map(lambda item: send_one(item, client), range(total_requests)))
        total_duration = time.perf_counter() - start_time
        latencies = [latency for latency, error in results if latency is not None]
        errors = sum(1 for _, error in results if error is not None)

        # Doğrulama: Kayıtlar gerçekten yazıldı mı?
        from storage import get_store
        verify_config = {
            "database_path": str(db_path),
            "storage": {"backend": "sqlite", "wal_mode": wal_mode},
        }
        counts = get_store(verify_config).count_summary("all")
        written_count = counts["total"]

        latencies.sort()
        avg_lat = sum(latencies) / len(latencies) if latencies else 0.0
        p50_lat = _percentile(latencies, 0.50)
        p95_lat = _percentile(latencies, 0.95)
        rps = len(latencies) / total_duration if total_duration > 0 else 0.0
        write_count_matches = written_count == len(latencies)

        return {
            "wal_mode": wal_mode,
            "total_requests": total_requests,
            "concurrency": concurrency,
            "total_duration_sec": total_duration,
            "successful_requests": len(latencies),
            "error_count": errors,
            "rps": rps,
            "avg_latency_ms": avg_lat,
            "p50_latency_ms": p50_lat,
            "p95_latency_ms": p95_lat,
            "written_count": written_count,
            "write_count_matches": write_count_matches,
        }

    finally:
        if server_process is not None:
            if server_process.poll() is None:
                try:
                    server_process.terminate()
                except OSError:
                    # Süreç aynı anda kapandıysa wait() yine de çıkışını toplar.
                    pass
            try:
                server_process.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                try:
                    server_process.kill()
                except OSError:
                    pass
                server_process.wait(timeout=3.0)
        # Başlatma başarısız olsa bile yalnızca bu koşumun geçici dosyalarını sil.
        for attempt in range(5):
            try:
                shutil.rmtree(temp_dir)
                break
            except FileNotFoundError:
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.1)


def _percentile(values: list[float], fraction: float) -> float:
    """Sıralı değerlerde doğrusal enterpolasyonla yüzdelik hesaplar."""
    if not values:
        return 0.0
    position = (len(values) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    portion = position - lower
    return values[lower] * (1 - portion) + values[upper] * portion


def main():
    parser = argparse.ArgumentParser(description="NetNabız Yük Testi Aracı")
    parser.add_argument("-n", "--requests", type=int, default=1000, help="Toplam istek sayısı (varsayılan: 1000)")
    parser.add_argument("-c", "--concurrency", type=int, default=20, help="Eşzamanlı istek iş parçacığı (varsayılan: 20)")
    parser.add_argument("--skip-nowal", action="store_true", help="Yalnızca WAL modunu test et")
    args = parser.parse_args()
    if args.requests < 1 or args.concurrency < 1:
        parser.error("--requests ve --concurrency en az 1 olmalı.")

    print("=" * 65)
    print("           NETNABIZ DEPOLAMA KATMANI YÜK TESTİ")
    print("=" * 65)
    print(f"Toplam İstek     : {args.requests}")
    print(f"Eşzamanlılık (C) : {args.concurrency}")
    print("Not: Bu test bu bilgisayarda, tek makinede, yerel ağ olmadan")
    print("     (loopback) çalıştırılır; sonuç API ve SQLite birlikteyken ölçülür.")
    print("-" * 65)

    print("\n[1/2] WAL Modu AÇIK (varsayılan üretim ayarı) test ediliyor...")
    wal_res = run_benchmark_pass(total_requests=args.requests, concurrency=args.concurrency, wal_mode=True)
    print(f" -> Tamamlandı. Süre: {wal_res['total_duration_sec']:.2f} s | RPS: {wal_res['rps']:.1f}")
    print(f"    Ort. Gecikme: {wal_res['avg_latency_ms']:.2f} ms | P50: {wal_res['p50_latency_ms']:.2f} ms | P95: {wal_res['p95_latency_ms']:.2f} ms")
    print(f"    Yazılan Kayıt: {wal_res['written_count']} / {wal_res['total_requests']} (Hata: {wal_res['error_count']})")
    print(f"    Başarılı istek-kayıt sayısı eşleşiyor: {'Evet' if wal_res['write_count_matches'] else 'Hayır'}")

    nowal_res = None
    if not args.skip_nowal:
        print("\n[2/2] WAL Modu KAPALI (klasik rollback journal) test ediliyor...")
        nowal_res = run_benchmark_pass(total_requests=args.requests, concurrency=args.concurrency, wal_mode=False)
        print(f" -> Tamamlandı. Süre: {nowal_res['total_duration_sec']:.2f} s | RPS: {nowal_res['rps']:.1f}")
        print(f"    Ort. Gecikme: {nowal_res['avg_latency_ms']:.2f} ms | P50: {nowal_res['p50_latency_ms']:.2f} ms | P95: {nowal_res['p95_latency_ms']:.2f} ms")
        print(f"    Yazılan Kayıt: {nowal_res['written_count']} / {nowal_res['total_requests']} (Hata: {nowal_res['error_count']})")
        print(f"    Başarılı istek-kayıt sayısı eşleşiyor: {'Evet' if nowal_res['write_count_matches'] else 'Hayır'}")

    print("\n" + "=" * 65)
    print("                    KARŞILAŞTIRMA ÖZETİ")
    print("=" * 65)
    print(f"{'Metrik':<25} | {'WAL Açık':<15} | {'WAL Kapalı':<15}")
    print("-" * 65)
    print(f"{'Toplam Süre (s)':<25} | {wal_res['total_duration_sec']:<15.2f} | {(nowal_res['total_duration_sec'] if nowal_res else 0):<15.2f}")
    print(f"{'İstek / Saniye (RPS)':<25} | {wal_res['rps']:<15.1f} | {(nowal_res['rps'] if nowal_res else 0):<15.1f}")
    print(f"{'Ortalama Gecikme (ms)':<25} | {wal_res['avg_latency_ms']:<15.2f} | {(nowal_res['avg_latency_ms'] if nowal_res else 0):<15.2f}")
    print(f"{'Medyan (%50) Gecikme (ms)':<25} | {wal_res['p50_latency_ms']:<15.2f} | {(nowal_res['p50_latency_ms'] if nowal_res else 0):<15.2f}")
    print(f"{'%95 Gecikme (ms)':<25} | {wal_res['p95_latency_ms']:<15.2f} | {(nowal_res['p95_latency_ms'] if nowal_res else 0):<15.2f}")
    print(f"{'Hata Sayısı':<25} | {wal_res['error_count']:<15} | {(nowal_res['error_count'] if nowal_res else 0):<15}")
    print(f"{'Doğrulanan Yazma':<25} | {wal_res['written_count']:<15} | {(nowal_res['written_count'] if nowal_res else 0):<15}")
    print("=" * 65)


if __name__ == "__main__":
    main()
