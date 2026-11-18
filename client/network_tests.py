"""TCP gecikme/kayıp ve HTTP üzerinden hız ölçümü yardımcıları."""

import asyncio
import socket
import statistics
import time
from typing import Optional

import httpx


def measure_tcp_latency_and_loss(
    target: str,
    attempts: int = 10,
    timeout: float = 2.0,
    debug: bool = False,
) -> tuple[Optional[float], Optional[float]]:
    """Hedefe TCP bağlantısı deneyip başarılı sürelerin medyanını ve hata oranını verir."""
    try:
        host, separator, port_text = target.rpartition(":")
        if not separator or not host or not port_text:
            return None, None
        if host.startswith("[") and host.endswith("]"):
            host = host[1:-1]
        port = int(port_text)
        if not 1 <= port <= 65535 or attempts < 1:
            return None, None
    except (TypeError, ValueError):
        return None, None

    successful_rtts = []
    failed_count = 0
    for index in range(attempts):
        started = time.perf_counter()
        try:
            with socket.create_connection((host, port), timeout=timeout):
                pass
            elapsed_ms = (time.perf_counter() - started) * 1000
            successful_rtts.append(elapsed_ms)
            if debug:
                print(f"  [TCP {index + 1}/{attempts}] {host}:{port} -> {elapsed_ms:.1f} ms")
        except OSError as error:
            failed_count += 1
            if debug:
                print(f"  [TCP {index + 1}/{attempts}] bağlantı başarısız: {error}")

    median_rtt = round(statistics.median(successful_rtts), 1) if successful_rtts else None
    loss_pct = round(failed_count / attempts * 100, 1)
    return median_rtt, loss_pct


async def _download_until_deadline(download_url: str, max_duration: float) -> Optional[float]:
    """HTTP akışını toplam süre sınırı içinde okuyup hızı hesaplar."""
    if not download_url or max_duration <= 0:
        return None

    client = httpx.AsyncClient(timeout=None)
    response = None
    started = time.perf_counter()
    try:
        request = client.build_request("GET", download_url)
        # İstek başlığı ve indirme gövdesi aynı toplam süre sınırını paylaşır.
        response = await asyncio.wait_for(
            client.send(request, stream=True), timeout=max_duration
        )
        if response.status_code != 200:
            return None

        total_bytes = 0
        chunks = response.aiter_bytes(chunk_size=65536).__aiter__()
        deadline = started + max_duration
        while True:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                break
            try:
                chunk = await asyncio.wait_for(chunks.__anext__(), timeout=remaining)
            except (asyncio.TimeoutError, StopAsyncIteration):
                break
            total_bytes += len(chunk)

        elapsed = time.perf_counter() - started
        if total_bytes == 0 or elapsed <= 0:
            return None
        return round(total_bytes * 8 / elapsed / 1_000_000, 2)
    finally:
        if response is not None:
            await response.aclose()
        await client.aclose()


def measure_download_speed(
    download_url: str,
    max_duration: float = 8.0,
    debug: bool = False,
) -> Optional[float]:
    """Akış halinde indirir; istenen toplam süre aşılırsa o ana kadarki hızı döndürür."""
    try:
        speed = asyncio.run(_download_until_deadline(download_url, max_duration))
        if debug:
            print(f"  [İndirme] {speed} Mbps" if speed is not None else "  [İndirme] ölçülemedi")
        return speed
    except Exception as error:
        if debug:
            print(f"  [İndirme] ölçüm hatası: {error}")
        return None


async def _upload_with_deadline(
    upload_url: str, payload: bytes, max_duration: float
) -> Optional[float]:
    """Veriyi HTTP ile gönderir ve toplam isteği süre sınırında iptal eder."""
    if not upload_url or max_duration <= 0:
        return None

    started = time.perf_counter()
    async with httpx.AsyncClient(timeout=None) as client:
        response = await asyncio.wait_for(
            client.post(upload_url, content=payload), timeout=max_duration
        )
    elapsed = time.perf_counter() - started
    if response.status_code not in (200, 201, 204) or elapsed <= 0:
        return None
    return round(len(payload) * 8 / elapsed / 1_000_000, 2)


def measure_upload_speed(
    upload_url: str,
    payload_size_mb: float = 2.0,
    max_duration: float = 8.0,
    debug: bool = False,
) -> Optional[float]:
    """Yaklaşık 2 MB veri yollar; istek toplam süre sınırını aşarsa None döner."""
    try:
        if payload_size_mb <= 0:
            return None
        payload = b"0" * int(payload_size_mb * 1024 * 1024)
        speed = asyncio.run(_upload_with_deadline(upload_url, payload, max_duration))
        if debug:
            print(f"  [Yükleme] {speed} Mbps" if speed is not None else "  [Yükleme] ölçülemedi")
        return speed
    except Exception as error:
        if debug:
            print(f"  [Yükleme] ölçüm hatası: {error}")
        return None


def run_network_tests(config: dict, debug: bool = False) -> dict:
    """Yapılandırmadaki hedeflerle ağ testlerini çalıştırır; test hatalarını None verir."""
    # Hedef adresler örnek ayar dosyasından gelir; kaynak kodda adres saklanmaz.
    latency_target = config.get("latency_target", "")
    download_url = config.get("download_url", "")
    upload_url = config.get("upload_url", "")

    rtt_ms, loss_pct = measure_tcp_latency_and_loss(
        target=latency_target, attempts=10, timeout=2.0, debug=debug
    )
    down_mbps = measure_download_speed(download_url, max_duration=8.0, debug=debug)
    up_mbps = measure_upload_speed(
        upload_url, payload_size_mb=2.0, max_duration=8.0, debug=debug
    )
    return {
        "rtt_ms": rtt_ms,
        "loss_pct": loss_pct,
        "down_mbps": down_mbps,
        "up_mbps": up_mbps,
    }
