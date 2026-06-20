from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import List, Optional, Dict, Any


class ColdMode(str, Enum):
    DIESEL = "diesel"
    ELECTRIC = "electric"
    OFF = "off"


class IgnitionStatus(str, Enum):
    ON = "on"
    OFF = "off"


class ChargeStatus(str, Enum):
    PLUGGED = "plugged"
    UNPLUGGED = "unplugged"


class OperationPhase(str, Enum):
    LOADING = "loading"
    TRANSPORT = "transport"
    UNLOADING = "unloading"
    WAITING = "waiting"


@dataclass
class Vehicle:
    plate: str
    fleet: str
    driver: str
    vehicle_type: str = "冷藏车"
    capacity: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plate": self.plate,
            "fleet": self.fleet,
            "driver": self.driver,
            "vehicle_type": self.vehicle_type,
            "capacity": self.capacity
        }


@dataclass
class TemperatureRecord:
    timestamp: datetime
    compartment: str
    temperature: float
    target_temperature: float = -18.0

    @property
    def deviation(self) -> float:
        return self.temperature - self.target_temperature

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "compartment": self.compartment,
            "temperature": self.temperature,
            "target_temperature": self.target_temperature,
            "deviation": self.deviation
        }


@dataclass
class FuelRecord:
    timestamp: datetime
    fuel_level: float
    fuel_consumption: float
    fuel_rate: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "fuel_level": self.fuel_level,
            "fuel_consumption": self.fuel_consumption,
            "fuel_rate": self.fuel_rate
        }


@dataclass
class ElectricRecord:
    timestamp: datetime
    battery_level: float
    power_consumption: float
    voltage: float = 0.0
    current: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "battery_level": self.battery_level,
            "power_consumption": self.power_consumption,
            "voltage": self.voltage,
            "current": self.current
        }


@dataclass
class ColdModeRecord:
    timestamp: datetime
    mode: ColdMode
    set_point: float = -18.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "mode": self.mode.value,
            "set_point": self.set_point
        }


@dataclass
class IgnitionRecord:
    timestamp: datetime
    status: IgnitionStatus

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "status": self.status.value
        }


@dataclass
class ChargeRecord:
    timestamp: datetime
    status: ChargeStatus
    charge_power: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "status": self.status.value,
            "charge_power": self.charge_power
        }


@dataclass
class RouteSegment:
    start_time: datetime
    end_time: datetime
    start_location: str
    end_location: str
    phase: OperationPhase
    distance: float = 0.0

    @property
    def duration(self) -> timedelta:
        return self.end_time - self.start_time

    def to_dict(self) -> Dict[str, Any]:
        return {
            "start_time": self.start_time.strftime("%Y-%m-%d %H:%M:%S"),
            "end_time": self.end_time.strftime("%Y-%m-%d %H:%M:%S"),
            "start_location": self.start_location,
            "end_location": self.end_location,
            "phase": self.phase.value,
            "distance": self.distance,
            "duration_minutes": self.duration.total_seconds() / 60
        }


@dataclass
class Trip:
    trip_id: str
    vehicle: Vehicle
    date: datetime
    route: str
    segments: List[RouteSegment] = field(default_factory=list)
    temperature_records: List[TemperatureRecord] = field(default_factory=list)
    fuel_records: List[FuelRecord] = field(default_factory=list)
    electric_records: List[ElectricRecord] = field(default_factory=list)
    cold_mode_records: List[ColdModeRecord] = field(default_factory=list)
    ignition_records: List[IgnitionRecord] = field(default_factory=list)
    charge_records: List[ChargeRecord] = field(default_factory=list)

    @property
    def total_fuel_consumption(self) -> float:
        if not self.fuel_records:
            return 0.0
        return self.fuel_records[-1].fuel_consumption - self.fuel_records[0].fuel_consumption

    @property
    def total_power_consumption(self) -> float:
        if not self.electric_records:
            return 0.0
        return sum(r.power_consumption for r in self.electric_records)

    @property
    def total_distance(self) -> float:
        return sum(s.distance for s in self.segments)

    def get_records_in_range(self, start: datetime, end: datetime, record_type: str) -> List[Any]:
        records = getattr(self, f"{record_type}_records", [])
        return [r for r in records if start <= r.timestamp <= end]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trip_id": self.trip_id,
            "vehicle": self.vehicle.to_dict(),
            "date": self.date.strftime("%Y-%m-%d"),
            "route": self.route,
            "total_fuel_consumption": self.total_fuel_consumption,
            "total_power_consumption": self.total_power_consumption,
            "total_distance": self.total_distance,
            "segments": [s.to_dict() for s in self.segments],
            "temperature_records": [r.to_dict() for r in self.temperature_records],
            "fuel_records": [r.to_dict() for r in self.fuel_records],
            "electric_records": [r.to_dict() for r in self.electric_records],
            "cold_mode_records": [r.to_dict() for r in self.cold_mode_records],
            "ignition_records": [r.to_dict() for r in self.ignition_records],
            "charge_records": [r.to_dict() for r in self.charge_records]
        }


@dataclass
class Anomaly:
    anomaly_type: str
    severity: str
    description: str
    timestamp: Optional[datetime] = None
    vehicle: Optional[Vehicle] = None
    segment: Optional[RouteSegment] = None
    details: Dict[str, Any] = field(default_factory=dict)
    fuel_saving_potential: float = 0.0
    risk_score: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "anomaly_type": self.anomaly_type,
            "severity": self.severity,
            "description": self.description,
            "timestamp": self.timestamp.strftime("%Y-%m-%d %H:%M:%S") if self.timestamp else None,
            "vehicle_plate": self.vehicle.plate if self.vehicle else None,
            "segment": self.segment.to_dict() if self.segment else None,
            "details": self.details,
            "fuel_saving_potential": self.fuel_saving_potential,
            "risk_score": self.risk_score
        }


@dataclass
class DailyReport:
    report_date: datetime
    fleet_summary: Dict[str, Any] = field(default_factory=dict)
    driver_summary: Dict[str, Any] = field(default_factory=dict)
    route_summary: Dict[str, Any] = field(default_factory=dict)
    anomalies: List[Anomaly] = field(default_factory=list)
    total_fuel_saving: float = 0.0
    total_risk_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_date": self.report_date.strftime("%Y-%m-%d"),
            "fleet_summary": self.fleet_summary,
            "driver_summary": self.driver_summary,
            "route_summary": self.route_summary,
            "anomalies_count": len(self.anomalies),
            "total_fuel_saving": self.total_fuel_saving,
            "total_risk_count": self.total_risk_count
        }
