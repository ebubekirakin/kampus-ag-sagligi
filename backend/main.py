"""
NetNabız FastAPI Ana Sunucu Modülü.
Ölçümleri alır, doğrular ve SQLite veritabanına kaydeder.
"""

from datetime import datetime, timezone
from typing import List, Optional
from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

from backend.config import load_config
from backend.database import get_connection, init_db

app = FastAPI(
    title="NetNabız API",
    description="Kampüs Wi-Fi Sağlığı Ölçüm ve İzleme API",
    version="1.0.0",
)


# Pydantic veri modeli: API'ye gelen JSON isteğinin doğrulanması
class MeasurementCreate(BaseModel):
    device_hash: str = Field(..., description="Cihaz kimliğinin SHA-256 hash değeri")
    source: str = Field(default="desktop", description="Ölçüm kaynağı: desktop, web veya android")
    ssid: Optional[str] = Field(default=None, description="Bağlı bulunulan Wi-Fi adı")
    bssid: Optional[str] = Field(default=None, description="Modem/Erişim noktası MAC adresi")
    rssi_dbm: Optional[float] = Field(default=None, description="Sinyal gücü (dBm)")
    rtt_ms: float = Field(..., ge=0.0, description="Gecikme (ping süresi ms)")
    loss_pct: float = Field(..., ge=0.0, le=100.0, description="Paket kaybı yüzdesi (0-100)")
    down_mbps: float = Field(..., ge=0.0, description="İndirme hızı (Mbps)")
    up_mbps: float = Field(..., ge=0.0, description="Yükleme hızı (Mbps)")
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
    x_api_key: Optional[str] = Header(default=None),
):
    """Yeni bir ölçüm kaydeder."""
    # Timestamp belirtilmemişse şu anki UTC zamanını kullan
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
                    measurement.device_hash,
                    measurement.source,
                    measurement.ssid,
                    measurement.bssid,
                    measurement.rssi_dbm,
                    measurement.rtt_ms,
                    measurement.loss_pct,
                    measurement.down_mbps,
                    measurement.up_mbps,
                    measurement.building,
                    measurement.floor,
                    measurement.zone,
                    measurement.campus_confidence,
                    measurement.is_verified,
                    measurement.is_simulated,
                    ts,
                ),
            )
            conn.commit()
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
):
    """Kayıtlı ölçümleri listeler."""
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
