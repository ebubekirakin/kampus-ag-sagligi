"""
NetNabız Yük Testi Aracı (tools/load_test.py).

Geçici bir konfigürasyon ve geçici bir veritabanı (data/loadtest.db) ile
izole bir uvicorn sunucusu başlatır. httpx ile eşzamanlı istekler göndererek
WAL modu açık ve kapalı durumdaki performansı (saniyedeki istek sayısı,
ortalama / medyan / %95 gecikme) ölçer ve doğrular.
"""

import argparse
import asyncio
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
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
    """Tek bir yük testi koşumunu (WAL açık veya kapalı) izole sunucu ile icra eder."""
    port = port or find_free_port()
    temp_dir = _BASE_DIR / "data" / f"loadtest_tmp_{'wal' if wal_mode else 'nowal'}"
    temp_dir.mkdir(parents=True, exist_ok=True)

    db_path = temp_dir / "loadtest.db"
    config_path = temp_dir / "config_loadtest.toml"

    # Geçici toml ayar dosyasını yaz
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

    # Çevre değişkenine geçici config yolunu ver
    server_env = os.environ.copy()
    server_env["NETNABIZ_CONFIG"] = str(config_path)

    python_executable = sys.executable

    server_process = subprocess.Popen(
        [
            python_executable,
            "-m",
            "uvicorn",
            "backend.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--no-access-log",
        ],
        cwd=str(_BASE_DIR),
        env=server_env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    base_url = f"http://127.0.0.1:{port}"

    try:
        # Sunucunun hazır olmasını bekle
        server_ready = False
        for _ in range(50):
            try:
                resp = httpx.get(f"{base_url}/health", timeout=1.0)
                if resp.status_code == 200:
                    server_ready = True
                    break
            except Exception:
                time.sleep(0.1)

        if not server_ready:
            raise RuntimeError(f"Yük testi için başlatılan sunucu {port} portunda hazır olamadı.")

        # Eşzamanlı istek gönderme döngüsü
        latencies = []
        errors = 0

        async def worker(queue: asyncio.Queue, client: httpx.AsyncClient):
            nonlocal errors
            while not queue.empty():
                try:
                    _ = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                payload = {
                    "device_hash": f"dev-loadtest-hash",
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
                headers = {"x-api-key": "loadtest-api-key"}
                t0 = time.perf_counter()
                try:
                    res = await client.post(f"{base_url}/measurements", json=payload, headers=headers)
                    dur_ms = (time.perf_counter() - t0) * 1000.0
                    if res.status_code in (200, 201):
                        latencies.append(dur_ms)
                    else:
                        errors += 1
                except Exception:
                    errors += 1

                finally:
                    queue.task_done()

        async def run_requests():
            queue = asyncio.Queue()
            for i in range(total_requests):
                queue.put_nowait(i)

            limits = httpx.Limits(max_connections=concurrency + 5, max_keepalive_connections=concurrency)
            async with httpx.AsyncClient(limits=limits, timeout=15.0) as client:
                tasks = [asyncio.create_task(worker(queue, client)) for _ in range(concurrency)]
                await asyncio.gather(*tasks)

        start_time = time.perf_counter()
        asyncio.run(run_requests())
        total_duration = time.perf_counter() - start_time

        # Doğrulama: Kayıtlar gerçekten yazıldı mı?
        from storage.sqlite_store import SQLiteMeasurementStore
        verify_store = SQLiteMeasurementStore(db_path=db_path)
        counts = verify_store.count_summary("all")
        written_count = counts["total"]

        latencies.sort()
        avg_lat = sum(latencies) / len(latencies) if latencies else 0.0
        p50_lat = latencies[int(len(latencies) * 0.50)] if latencies else 0.0
        p95_lat = latencies[int(len(latencies) * 0.95)] if latencies else 0.0
        rps = len(latencies) / total_duration if total_duration > 0 else 0.0

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
        }

    finally:
        server_process.terminate()
        try:
            server_process.wait(timeout=3.0)
        except Exception:
            server_process.kill()

        # Temizlik
        shutil.rmtree(temp_dir, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description="NetNabız Yük Testi Aracı")
    parser.add_argument("-n", "--requests", type=int, default=1000, help="Toplam istek sayısı (varsayılan: 1000)")
    parser.add_argument("-c", "--concurrency", type=int, default=20, help="Eşzamanlı istek iş parçacığı (varsayılan: 20)")
    parser.add_argument("--skip-nowal", action="store_true", help="Yalnızca WAL modunu test et")
    args = parser.parse_args()

    print("=" * 65)
    print("           NETNABIZ DEPOLAMA KATMANI YÜK TESTİ")
    print("=" * 65)
    print(f"Toplam İstek     : {args.requests}")
    print(f"Eşzamanlılık (C) : {args.concurrency}")
    print("Not: Bu test bu bilgisayarda, tek makinede, yerel ağ olmadan")
    print("     (loopback) çalıştırılarak ham depolama hızı ölçülmektedir.")
    print("-" * 65)

    print("\n[1/2] WAL Modu AÇIK (varsayılan üretim ayarı) test ediliyor...")
    wal_res = run_benchmark_pass(total_requests=args.requests, concurrency=args.concurrency, wal_mode=True)
    print(f" -> Tamamlandı. Süre: {wal_res['total_duration_sec']:.2f} s | RPS: {wal_res['rps']:.1f}")
    print(f"    Ort. Gecikme: {wal_res['avg_latency_ms']:.2f} ms | P50: {wal_res['p50_latency_ms']:.2f} ms | P95: {wal_res['p95_latency_ms']:.2f} ms")
    print(f"    Yazılan Kayıt: {wal_res['written_count']} / {wal_res['total_requests']} (Hata: {wal_res['error_count']})")

    nowal_res = None
    if not args.skip_nowal:
        print("\n[2/2] WAL Modu KAPALI (klasik rollback journal) test ediliyor...")
        nowal_res = run_benchmark_pass(total_requests=args.requests, concurrency=args.concurrency, wal_mode=False)
        print(f" -> Tamamlandı. Süre: {nowal_res['total_duration_sec']:.2f} s | RPS: {nowal_res['rps']:.1f}")
        print(f"    Ort. Gecikme: {nowal_res['avg_latency_ms']:.2f} ms | P50: {nowal_res['p50_latency_ms']:.2f} ms | P95: {nowal_res['p95_latency_ms']:.2f} ms")
        print(f"    Yazılan Kayıt: {nowal_res['written_count']} / {nowal_res['total_requests']} (Hata: {nowal_res['error_count']})")

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
