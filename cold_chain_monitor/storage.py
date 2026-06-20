import json
import os
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from .models import Trip, Vehicle, DailyReport


class DataStorage:
    def __init__(self, base_dir: str = "./data"):
        self.base_dir = base_dir
        self.raw_dir = os.path.join(base_dir, "raw")
        self.processed_dir = os.path.join(base_dir, "processed")
        self.exports_dir = os.path.join(base_dir, "exports")
        self._ensure_dirs()

    def _ensure_dirs(self):
        for d in [self.base_dir, self.raw_dir, self.processed_dir, self.exports_dir]:
            os.makedirs(d, exist_ok=True)

    def save_trip(self, trip: Trip) -> str:
        filename = f"{trip.trip_id}.json"
        filepath = os.path.join(self.processed_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(trip.to_dict(), f, ensure_ascii=False, indent=2)
        return filepath

    def load_trip(self, trip_id: str) -> Optional[Dict]:
        filepath = os.path.join(self.processed_dir, f"{trip_id}.json")
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        return None

    def list_trips(self) -> List[str]:
        if not os.path.exists(self.processed_dir):
            return []
        return [f.replace(".json", "") for f in os.listdir(self.processed_dir) if f.endswith(".json")]

    def list_raw_files(self) -> List[str]:
        if not os.path.exists(self.raw_dir):
            return []
        return [f for f in os.listdir(self.raw_dir) if f.endswith((".csv", ".json"))]

    def get_raw_file_path(self, filename: str) -> str:
        return os.path.join(self.raw_dir, filename)

    def save_report(self, report: DailyReport, format: str = "json") -> str:
        date_str = report.report_date.strftime("%Y-%m-%d")
        if format == "json":
            filename = f"daily_report_{date_str}.json"
            filepath = os.path.join(self.exports_dir, filename)
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)
        elif format == "csv":
            filename = f"daily_report_{date_str}.csv"
            filepath = os.path.join(self.exports_dir, filename)
            self._save_report_csv(report, filepath)
        else:
            raise ValueError(f"Unsupported format: {format}")
        return filepath

    def _save_report_csv(self, report: DailyReport, filepath: str):
        import csv
        with open(filepath, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["冷链运输联控日志 - 日报"])
            writer.writerow(["报告日期", report.report_date.strftime("%Y-%m-%d")])
            writer.writerow([])

            writer.writerow(["一、车队汇总"])
            writer.writerow(["车队", "车辆数", "总油耗(L)", "总电耗(kWh)", "节油潜力(L)", "温控风险数"])
            for fleet, data in report.fleet_summary.items():
                writer.writerow([
                    fleet,
                    data.get("vehicle_count", 0),
                    data.get("total_fuel", 0),
                    data.get("total_power", 0),
                    data.get("fuel_saving", 0),
                    data.get("risk_count", 0)
                ])
            writer.writerow([])

            writer.writerow(["二、司机汇总"])
            writer.writerow(["司机", "车队", "车牌", "油耗(L)", "电耗(kWh)", "节油潜力(L)", "温控风险数"])
            for driver, data in report.driver_summary.items():
                writer.writerow([
                    driver,
                    data.get("fleet", ""),
                    data.get("plate", ""),
                    data.get("total_fuel", 0),
                    data.get("total_power", 0),
                    data.get("fuel_saving", 0),
                    data.get("risk_count", 0)
                ])
            writer.writerow([])

            writer.writerow(["三、路线汇总"])
            writer.writerow(["路线", "车次", "总里程(km)", "平均油耗(L/100km)", "节油潜力(L)", "温控风险数"])
            for route, data in report.route_summary.items():
                writer.writerow([
                    route,
                    data.get("trip_count", 0),
                    data.get("total_distance", 0),
                    data.get("avg_fuel_per_100km", 0),
                    data.get("fuel_saving", 0),
                    data.get("risk_count", 0)
                ])
            writer.writerow([])

            writer.writerow(["四、异常详情"])
            writer.writerow(["类型", "严重程度", "车牌", "时间", "描述", "节油潜力(L)", "风险评分"])
            for anomaly in report.anomalies:
                writer.writerow([
                    anomaly.anomaly_type,
                    anomaly.severity,
                    anomaly.vehicle.plate if anomaly.vehicle else "",
                    anomaly.timestamp.strftime("%Y-%m-%d %H:%M:%S") if anomaly.timestamp else "",
                    anomaly.description,
                    anomaly.fuel_saving_potential,
                    anomaly.risk_score
                ])

    def get_vehicle_list(self) -> List[Tuple[str, str]]:
        trips = self.list_trips()
        vehicles = set()
        for trip_id in trips:
            data = self.load_trip(trip_id)
            if data:
                vehicle = data.get("vehicle", {})
                plate = vehicle.get("plate", "")
                date = data.get("date", "")
                vehicles.add((plate, date))
        return sorted(vehicles, key=lambda x: (x[1], x[0]))

    def get_trips_by_date(self, date: datetime) -> List[str]:
        date_str = date.strftime("%Y-%m-%d")
        trips = []
        for trip_id in self.list_trips():
            data = self.load_trip(trip_id)
            if data and data.get("date") == date_str:
                trips.append(trip_id)
        return trips

    def get_trips_by_plate(self, plate: str) -> List[str]:
        trips = []
        for trip_id in self.list_trips():
            data = self.load_trip(trip_id)
            if data and data.get("vehicle", {}).get("plate") == plate:
                trips.append(trip_id)
        return trips

    def clear_processed_data(self):
        for f in os.listdir(self.processed_dir):
            if f.endswith(".json"):
                os.remove(os.path.join(self.processed_dir, f))
