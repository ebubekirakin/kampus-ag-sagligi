"""
NetNabız FastAPI Ana Sunucu Modülü.
Ölçümleri alır, doğrular ve SQLite veritabanına kaydeder.
"""

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
from ipaddress import ip_address, ip_network
from secrets import compare_digest
from typing import Literal, Optional
from fastapi import FastAPI, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator

from backend.config import load_config
from backend.database import get_connection, init_db
from project_utils import parse_building_floor

app = FastAPI(
    title="NetNabız API",
    description="Kampüs Wi-Fi Sağlığı Ölçüm ve İzleme API",
    version="1.0.0",
)


# Pydantic veri modeli: API'ye gelen JSON isteğinin doğrulanması
class MeasurementCreate(BaseModel):
    device_hash: str = Field(..., description="Cihaz kimliğinin SHA-256 hash değeri")
    source: Literal["desktop", "web", "android"] = Field(
        default="desktop", description="Ölçüm kaynağı: desktop, web veya android"
    )
    ssid: Optional[str] = Field(default=None, description="Bağlı bulunulan Wi-Fi adı")
    bssid: Optional[str] = Field(default=None, description="Modem/Erişim noktası MAC adresi")
    rssi_dbm: Optional[float] = Field(default=None, description="Sinyal gücü (dBm)")
    rtt_ms: Optional[float] = Field(default=None, ge=0.0, description="Gecikme (ping süresi ms)")
    loss_pct: Optional[float] = Field(default=None, ge=0.0, le=100.0, description="Paket kaybı yüzdesi (0-100)")
    down_mbps: Optional[float] = Field(default=None, ge=0.0, description="İndirme hızı (Mbps)")
    up_mbps: Optional[float] = Field(default=None, ge=0.0, description="Yükleme hızı (Mbps)")
    building: Optional[str] = Field(default=None, description="Bina adı")
    floor: Optional[str] = Field(default=None, description="Kat bilgisi")
    zone: str = Field(..., description="Bölge adı")
    campus_confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Kampüs ağı güven skoru (0.0 - 1.0)")
    is_verified: int = Field(default=1, ge=0, le=1, description="Doğrulanmış kampüs ölçümü mü (1 veya 0)")
    is_simulated: int = Field(
        default=0,
        ge=0,
        le=1,
        description="Simülasyon verisi mi (1) gerçek ölçüm mü (0)",
    )
    timestamp: Optional[str] = Field(default=None, description="Ölçüm zamanı (ISO 8601 formatı)")

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, value: Optional[str]) -> Optional[str]:
        if not value or not value.strip():
            return None
        try:
            parsed_dt = datetime.fromisoformat(value.strip())
        except Exception as exc:
            raise ValueError(f"Geçersiz ISO 8601 zaman damgası: {value}") from exc

        # Zaman damgasını UTC'ye standardize et
        if parsed_dt.tzinfo is None:
            utc_dt = parsed_dt.replace(tzinfo=timezone.utc)
        else:
            utc_dt = parsed_dt.astimezone(timezone.utc)

        # Gelecekte 5 dakikadan fazla ileri zamanlı olamaz
        max_future = datetime.now(timezone.utc) + timedelta(minutes=5)
        if utc_dt > max_future:
            raise ValueError("Ölçüm zamanı gelecekte 5 dakikadan fazla ileri olamaz.")

        return utc_dt.isoformat()


def hash_device_id(device_hash: str, salt: str) -> str:
    """İstemciden gelen device_hash değerini sunucudaki hash_salt ile HMAC-SHA256 kullanarak yeniden hash'ler."""
    return hmac.new(
        salt.encode("utf-8"), device_hash.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def calculate_campus_confidence(client_ip: Optional[str], config: dict) -> float:
    """
    İstek yapan istemcinin IP adresine göre kampüs ağında olma güven skorunu hesaplar.
    X-Forwarded-For başlığı taklit edilebileceğinden dikkate alınmaz.
    """
    if not client_ip:
        return 0.0

    dev_mode = config.get("dev_mode", False)
    if dev_mode and client_ip in ("127.0.0.1", "::1", "localhost", "testclient"):
        return 1.0

    try:
        ip = ip_address(client_ip)
    except ValueError:
        return 0.0

    campus_ranges = config.get("campus_ip_ranges", [])
    for cidr in campus_ranges:
        try:
            if ip in ip_network(cidr):
                return 1.0
        except ValueError:
            continue

    return 0.0


def check_api_key(supplied_key: Optional[str]) -> None:
    """Ölçüm verisine erişmeden önce ortak anahtarı doğrular."""
    expected_key = load_config().get("api_key", "")
    supplied_bytes = supplied_key.encode("utf-8") if supplied_key else b""
    expected_bytes = expected_key.encode("utf-8") if expected_key else b""
    if not expected_bytes or not supplied_bytes or not compare_digest(supplied_bytes, expected_bytes):
        raise HTTPException(status_code=401, detail="Geçersiz veya eksik API anahtarı.")


@app.on_event("startup")
def startup_event():
    """Uygulama başladığında veritabanı tablosunu hazırla."""
    init_db()


@app.get("/health")
def health_check():
    """Sistemin ayakta olduğunu teyit eden sağlık kontrolü."""
    return {"status": "ok"}


@app.get("/zones")
def list_zones():
    """Tanımlı kampüs bölgelerinin listesini döner."""
    config = load_config()
    return config.get("zones", [])


@app.post("/measurements", status_code=201)
def create_measurement(
    measurement: MeasurementCreate,
    request: Request,
    x_api_key: Optional[str] = Header(default=None),
):
    """Yeni bir ölçüm kaydeder."""
    check_api_key(x_api_key)
    config = load_config()

    # Bölge kontrolü (config'teki zones listesinde olmalı; yoksa 422)
    allowed_zones = config.get("zones", [])
    if not allowed_zones or measurement.zone not in allowed_zones:
        raise HTTPException(
            status_code=422,
            detail=(
                "Ayar dosyasında geçerli bölge tanımlanmamış."
                if not allowed_zones
                else f"Geçersiz bölge: '{measurement.zone}'. Tanımlı bölgelerden biri seçilmelidir."
            ),
        )

    # Building ve floor boşsa zone adından otomatik türet
    building = measurement.building
    floor = measurement.floor
    if not building or not floor:
        parsed_b, parsed_f = parse_building_floor(measurement.zone)
        building = building or parsed_b
        floor = floor or parsed_f

    # Cihaz hash'ini sunucu tarafındaki hash_salt ile HMAC-SHA256 yaparak sakla
    salt = config.get("hash_salt", "")
    stored_device_hash = hash_device_id(measurement.device_hash, salt)

    # campus_confidence ve is_verified sunucuda hesaplanır
    if measurement.is_simulated == 0:
        # Gerçek ölçüm: İstemciden gelen güven ve doğrulama değerleri YOK SAYILIR.
        # İstek IP'sine bakılır (X-Forwarded-For kullanılmaz).
        client_ip = request.client.host if request.client else None
        campus_confidence = calculate_campus_confidence(client_ip, config)
        is_verified = 1 if campus_confidence >= 0.5 else 0
    else:
        # is_simulated == 1: Simülasyonun kampüs dışı test senaryolarını temsil edebilmesi için
        # gönderilen değerler olduğu gibi kabul edilir.
        campus_confidence = (
            measurement.campus_confidence
            if measurement.campus_confidence is not None
            else 1.0
        )
        is_verified = (
            measurement.is_verified
            if measurement.is_verified is not None
            else (1 if campus_confidence >= 0.5 else 0)
        )

    # Zaman damgası: boşsa sunucu anı (UTC)
    ts = measurement.timestamp or datetime.now(timezone.utc).isoformat()

    insert_sql = """
    INSERT INTO measurements (
        device_hash, source, ssid, bssid, rssi_dbm,
        rtt_ms, loss_pct, down_mbps, up_mbps,
        building, floor, zone, campus_confidence,
        is_verified, is_simulated, timestamp
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                insert_sql,
                (
                    stored_device_hash,
                    measurement.source,
                    measurement.ssid,
                    measurement.bssid,
                    measurement.rssi_dbm,
                    measurement.rtt_ms,
                    measurement.loss_pct,
                    measurement.down_mbps,
                    measurement.up_mbps,
                    building,
                    floor,
                    measurement.zone,
                    campus_confidence,
                    is_verified,
                    measurement.is_simulated,
                    ts,
                ),
            )
            record_id = cursor.lastrowid
            return {"status": "created", "id": record_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Kayıt hatası: {str(e)}")


@app.get("/measurements")
def list_measurements(
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    is_simulated: Optional[int] = Query(default=None, description="0: Gerçek, 1: Simüle"),
    zone: Optional[str] = Query(default=None, description="Bölge filtresi"),
    x_api_key: Optional[str] = Header(default=None),
):
    """Paylaşılan anahtarla yetkilendirilmiş isteklere ölçümleri döner."""
    check_api_key(x_api_key)
    query = "SELECT * FROM measurements WHERE 1=1"
    params = []

    if is_simulated is not None:
        query += " AND is_simulated = ?"
        params.append(is_simulated)

    if zone is not None:
        query += " AND zone = ?"
        params.append(zone)

    query += " ORDER BY id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]
