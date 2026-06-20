import csv
import json
import os
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
import uuid

from .models import (
    Trip, Vehicle, TemperatureRecord, FuelRecord, ElectricRecord,
    ColdModeRecord, IgnitionRecord, ChargeRecord, RouteSegment,
    ColdMode, IgnitionStatus, ChargeStatus, OperationPhase
)
from .storage import DataStorage


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


class DataImporter:
    def __init__(self, storage: DataStorage):
        self.storage = storage

    def import_all(self, clear_existing: bool = False) -> Tuple[int, List[str]]:
        if clear_existing:
            self.storage.clear_processed_data()

        raw_files = self.storage.list_raw_files()
        if not raw_files:
            return 0, []

        imported = 0
        errors = []

        for filename in raw_files:
            try:
                filepath = self.storage.get_raw_file_path(filename)
                trips = self._parse_file(filepath)
                for trip in trips:
                    self.storage.save_trip(trip)
                    imported += 1
            except Exception as e:
                errors.append(f"{filename}: {str(e)}")

        return imported, errors

    def import_file(self, filepath: str) -> Tuple[int, List[str]]:
        if not os.path.exists(filepath):
            return 0, [f"文件不存在: {filepath}"]

        try:
            trips = self._parse_file(filepath)
            for trip in trips:
                self.storage.save_trip(trip)
            return len(trips), []
        except Exception as e:
            return 0, [f"{os.path.basename(filepath)}: {str(e)}"]

    def _parse_file(self, filepath: str) -> List[Trip]:
        ext = os.path.splitext(filepath)[1].lower()
        if ext == ".csv":
            return self._parse_csv(filepath)
        elif ext == ".json":
            return self._parse_json(filepath)
        else:
            raise ValueError(f"不支持的文件格式: {ext}")

    def _parse_csv(self, filepath: str) -> List[Trip]:
        trips = {}
        current_trip_id = None

        with open(filepath, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                trip_id = row.get("trip_id") or row.get("行程ID")
                if not trip_id:
                    trip_id = self._generate_trip_id(row)

                if trip_id not in trips:
                    trips[trip_id] = self._create_trip_from_row(row, trip_id)

                trip = trips[trip_id]
                self._add_record_to_trip(trip, row)

        return list(trips.values())

    def _parse_json(self, filepath: str) -> List[Trip]:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict):
            data = [data]

        trips = []
        for item in data:
            trip = self._create_trip_from_dict(item)
            trips.append(trip)

        return trips

    def _generate_trip_id(self, row: Dict[str, Any]) -> str:
        plate = row.get("plate") or row.get("车牌", "")
        date = row.get("date") or row.get("日期", "")
        route = row.get("route") or row.get("路线", "")
        return f"{plate}_{date}_{route}_{uuid.uuid4().hex[:8]}"

    def _create_trip_from_row(self, row: Dict[str, Any], trip_id: str) -> Trip:
        plate = row.get("plate") or row.get("车牌", "未知")
        fleet = row.get("fleet") or row.get("车队", "未知")
        driver = row.get("driver") or row.get("司机", "未知")
        date_str = row.get("date") or row.get("日期", "")
        route = row.get("route") or row.get("路线", "未知")

        try:
            date = datetime.strptime(date_str, "%Y-%m-%d") if date_str else datetime.now()
        except ValueError:
            date = datetime.now()

        vehicle = Vehicle(plate=plate, fleet=fleet, driver=driver)
        return Trip(trip_id=trip_id, vehicle=vehicle, date=date, route=route)

    def _create_trip_from_dict(self, data: Dict[str, Any]) -> Trip:
        trip_id = data.get("trip_id", f"trip_{uuid.uuid4().hex[:12]}")

        vehicle_data = data.get("vehicle", {})
        vehicle = Vehicle(
            plate=vehicle_data.get("plate", "未知"),
            fleet=vehicle_data.get("fleet", "未知"),
            driver=vehicle_data.get("driver", "未知")
        )

        date_str = data.get("date", "")
        try:
            date = datetime.strptime(date_str, "%Y-%m-%d") if date_str else datetime.now()
        except ValueError:
            date = datetime.now()

        trip = Trip(
            trip_id=trip_id,
            vehicle=vehicle,
            date=date,
            route=data.get("route", "未知")
        )

        for seg_data in data.get("segments", []):
            segment = RouteSegment(
                start_time=datetime.strptime(seg_data["start_time"], "%Y-%m-%d %H:%M:%S"),
                end_time=datetime.strptime(seg_data["end_time"], "%Y-%m-%d %H:%M:%S"),
                start_location=seg_data.get("start_location", ""),
                end_location=seg_data.get("end_location", ""),
                phase=OperationPhase(seg_data.get("phase", "transport")),
                distance=seg_data.get("distance", 0.0)
            )
            trip.segments.append(segment)

        for rec in data.get("temperature_records", []):
            trip.temperature_records.append(TemperatureRecord(
                timestamp=datetime.strptime(rec["timestamp"], "%Y-%m-%d %H:%M:%S"),
                compartment=rec.get("compartment", "主厢"),
                temperature=rec["temperature"],
                target_temperature=rec.get("target_temperature", -18.0)
            ))

        for rec in data.get("fuel_records", []):
            trip.fuel_records.append(FuelRecord(
                timestamp=datetime.strptime(rec["timestamp"], "%Y-%m-%d %H:%M:%S"),
                fuel_level=rec.get("fuel_level", 0.0),
                fuel_consumption=rec.get("fuel_consumption", 0.0),
                fuel_rate=rec.get("fuel_rate", 0.0)
            ))

        for rec in data.get("electric_records", []):
            trip.electric_records.append(ElectricRecord(
                timestamp=datetime.strptime(rec["timestamp"], "%Y-%m-%d %H:%M:%S"),
                battery_level=rec.get("battery_level", 0.0),
                power_consumption=rec.get("power_consumption", 0.0),
                voltage=rec.get("voltage", 0.0),
                current=rec.get("current", 0.0)
            ))

        for rec in data.get("cold_mode_records", []):
            trip.cold_mode_records.append(ColdModeRecord(
                timestamp=datetime.strptime(rec["timestamp"], "%Y-%m-%d %H:%M:%S"),
                mode=ColdMode(rec.get("mode", "diesel")),
                set_point=rec.get("set_point", -18.0)
            ))

        for rec in data.get("ignition_records", []):
            trip.ignition_records.append(IgnitionRecord(
                timestamp=datetime.strptime(rec["timestamp"], "%Y-%m-%d %H:%M:%S"),
                status=IgnitionStatus(rec.get("status", "off"))
            ))

        for rec in data.get("charge_records", []):
            trip.charge_records.append(ChargeRecord(
                timestamp=datetime.strptime(rec["timestamp"], "%Y-%m-%d %H:%M:%S"),
                status=ChargeStatus(rec.get("status", "unplugged")),
                charge_power=rec.get("charge_power", 0.0)
            ))

        return trip

    def _add_record_to_trip(self, trip: Trip, row: Dict[str, Any]):
        timestamp_str = row.get("timestamp") or row.get("时间")
        if not timestamp_str:
            return

        try:
            timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            try:
                timestamp = datetime.strptime(timestamp_str, "%Y/%m/%d %H:%M:%S")
            except ValueError:
                return

        record_type = row.get("record_type") or row.get("记录类型", "")

        if "温度" in record_type or "temperature" in record_type.lower():
            trip.temperature_records.append(TemperatureRecord(
                timestamp=timestamp,
                compartment=row.get("compartment") or row.get("厢体", "主厢"),
                temperature=_safe_float(row.get("temperature") or row.get("温度"), 0),
                target_temperature=_safe_float(row.get("target_temperature") or row.get("目标温度"), -18.0)
            ))
        elif "油耗" in record_type or "fuel" in record_type.lower():
            trip.fuel_records.append(FuelRecord(
                timestamp=timestamp,
                fuel_level=_safe_float(row.get("fuel_level") or row.get("油量"), 0),
                fuel_consumption=_safe_float(row.get("fuel_consumption") or row.get("累计油耗"), 0),
                fuel_rate=_safe_float(row.get("fuel_rate") or row.get("瞬时油耗"), 0)
            ))
        elif "电耗" in record_type or "electric" in record_type.lower() or "power" in record_type.lower():
            trip.electric_records.append(ElectricRecord(
                timestamp=timestamp,
                battery_level=_safe_float(row.get("battery_level") or row.get("电量"), 0),
                power_consumption=_safe_float(row.get("power_consumption") or row.get("电耗"), 0),
                voltage=_safe_float(row.get("voltage") or row.get("电压"), 0),
                current=_safe_float(row.get("current") or row.get("电流"), 0)
            ))
        elif "冷机模式" in record_type or "cold_mode" in record_type.lower():
            mode_str = row.get("mode") or row.get("模式", "diesel")
            mode = ColdMode.ELECTRIC if "电" in mode_str or "electric" in mode_str.lower() else ColdMode.DIESEL
            trip.cold_mode_records.append(ColdModeRecord(
                timestamp=timestamp,
                mode=mode,
                set_point=_safe_float(row.get("set_point") or row.get("设定温度"), -18.0)
            ))
        elif "点火" in record_type or "ignition" in record_type.lower():
            status_str = row.get("status") or row.get("状态", "off")
            status = IgnitionStatus.ON if "on" in status_str.lower() or "开" in status_str else IgnitionStatus.OFF
            trip.ignition_records.append(IgnitionRecord(
                timestamp=timestamp,
                status=status
            ))
        elif "插电" in record_type or "charge" in record_type.lower():
            status_str = row.get("status") or row.get("状态", "unplugged")
            status = ChargeStatus.PLUGGED if "plug" in status_str.lower() or "插" in status_str else ChargeStatus.UNPLUGGED
            trip.charge_records.append(ChargeRecord(
                timestamp=timestamp,
                status=status,
                charge_power=_safe_float(row.get("charge_power") or row.get("充电功率"), 0)
            ))
        elif "路段" in record_type or "segment" in record_type.lower():
            end_time_str = row.get("end_time") or row.get("结束时间", "")
            if end_time_str:
                try:
                    end_time = datetime.strptime(end_time_str, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    end_time = timestamp
            else:
                end_time = timestamp

            phase_str = row.get("phase") or row.get("阶段", "transport")
            if "装" in phase_str:
                phase = OperationPhase.LOADING
            elif "卸" in phase_str:
                phase = OperationPhase.UNLOADING
            elif "等" in phase_str:
                phase = OperationPhase.WAITING
            else:
                phase = OperationPhase.TRANSPORT

            trip.segments.append(RouteSegment(
                start_time=timestamp,
                end_time=end_time,
                start_location=row.get("start_location") or row.get("起点", ""),
                end_location=row.get("end_location") or row.get("终点", ""),
                phase=phase,
                distance=_safe_float(row.get("distance") or row.get("距离"), 0)
            ))
