"""
Ağ Performansı Ölçüm Modülü.
Yönetici izni gerektirmeyen TCP ping ile gecikme/paket kaybı ölçümü
ve HTTP akışı üzerinden indirme/yükleme hız testlerini gerçekleştirir.
"""

import socket
import statistics
import time
from typing import Optional
import httpx


def measure_tcp_latency_and_loss(
    target: str = "1.1.1.1:443",
    attempts: int = 10,
    timeout: float = 2.0,
    debug: bool = False,
) -> tuple[Optional[float], float]:
    """
    ICMP ping yerine hedef adrese TCP el sıkışması yaparak gecikmeyi ve yaklaşık paket kaybını ölçer.
    Windows'ta standart kullanıcı yetkileriyle sorunsuz çalışır.
    
    Dönüş: (medyan_rtt_ms, kayip_yuzdesi)
    """
    if ":" in target:
        host, port_str = target.split(":", 1)
        port = int(port_str)
    else:
        host = target
        port = 443

    successful_rtts = []
    failed_count = 0

    for i in range(attempts):
        t0 = time.perf_counter()
        try:
            sock = socket.create_connection((host, port), timeout=timeout)
            sock.close()
            t1 = time.perf_counter()
            rtt = (t1 - t0) * 1000.0  # ms cinsine çevir
            successful_rtts.append(rtt)
            if debug:
                print(f"  [TCP Ping {i+1}/{attempts}] {host}:{port} -> {rtt:.1f} ms")
        except Exception as exc:
            failed_count += 1
            if debug:
                print(f"  [TCP Ping {i+1}/{attempts}] {host}:{port} -> BAŞARISIZ ({exc})")

    # Medyan gecikme hesabı
    if successful_rtts:
        median_rtt = round(statistics.median(successful_rtts), 1)
    else:
        median_rtt = None

    # Yaklaşık paket kaybı oranı (%)
    loss_pct = round((failed_count / float(attempts)) * 100.0, 1)

    return median_rtt, loss_pct


def measure_download_speed(
    download_url: str,
    max_duration: float = 8.0,
    debug: bool = False,
) -> Optional[float]:
    """
    Belirtilen URL'den akış (stream) olarak veri indirir ve indirme hızını (Mbps) hesaplar.
    En fazla max_duration (varsayılan 8) saniye sürer.
    """
    if not download_url:
        return None

    try:
        total_bytes = 0
        start_time = time.perf_counter()

        with httpx.stream("GET", download_url, timeout=max_duration + 2.0) as response:
            if response.status_code != 200:
                if debug:
                    print(f"  [İndirme Testi] Beklenmeyen HTTP kodu: {response.status_code}")
                return None

            for chunk in response.iter_bytes(chunk_size=65536):
                total_bytes += len(chunk)
                elapsed = time.perf_counter() - start_time
                if elapsed >= max_duration:
                    break

        total_duration = time.perf_counter() - start_time
        if total_duration <= 0 or total_bytes == 0:
            return None

        # Byte to Megabit: (bytes * 8) / (süre * 1_000_000)
        mbps = (total_bytes * 8.0) / (total_duration * 1_000_000.0)
        speed = round(mbps, 2)
        if debug:
            print(f"  [İndirme Testi] {total_bytes / 1024 / 1024:.2f} MB indirildi, Hız: {speed} Mbps")
        return speed
    except Exception as exc:
        if debug:
            print(f"  [İndirme Testi Hatası] {exc}")
        return None


def measure_upload_speed(
    upload_url: str,
    payload_size_mb: float = 2.0,
    max_duration: float = 8.0,
    debug: bool = False,
) -> Optional[float]:
    """
    Belirtilen URL'ye yaklaşık 2 MB veri yükler ve yükleme hızını (Mbps) hesaplar.
    """
    if not upload_url:
        return None

    try:
        num_bytes = int(payload_size_mb * 1024 * 1024)
        payload = b"0" * num_bytes

        start_time = time.perf_counter()
        response = httpx.post(upload_url, content=payload, timeout=max_duration)

        total_duration = time.perf_counter() - start_time
        if response.status_code not in (200, 201, 204):
            if debug:
                print(f"  [Yükleme Testi] Beklenmeyen HTTP kodu: {response.status_code}")
            return None

        if total_duration <= 0:
            return None

        mbps = (num_bytes * 8.0) / (total_duration * 1_000_000.0)
        speed = round(mbps, 2)
        if debug:
            print(f"  [Yükleme Testi] {payload_size_mb:.1f} MB yüklendi, Hız: {speed} Mbps")
        return speed
    except Exception as exc:
        if debug:
            print(f"  [Yükleme Testi Hatası] {exc}")
        return None


def run_network_tests(config: dict, debug: bool = False) -> dict:
    """
    Tüm ağ testlerini (gecikme, paket kaybı, indirme, yükleme) sırayla yürütür.
    Hiçbir adımda çökmez, ölçülemeyen alanları None olarak döner.
    """
    latency_target = config.get("latency_target", "1.1.1.1:443")
    download_url = config.get("download_url", "https://speed.cloudflare.com/__down?bytes=5000000")
    upload_url = config.get("upload_url", "https://speed.cloudflare.com/__up")

    rtt_ms, loss_pct = measure_tcp_latency_and_loss(
        target=latency_target, attempts=10, timeout=2.0, debug=debug
    )
    down_mbps = measure_download_speed(download_url=download_url, max_duration=8.0, debug=debug)
    up_mbps = measure_upload_speed(upload_url=upload_url, payload_size_mb=2.0, max_duration=8.0, debug=debug)

    return {
        "rtt_ms": rtt_ms,
        "loss_pct": loss_pct,
        "down_mbps": down_mbps,
        "up_mbps": up_mbps,
    }
