from datetime import datetime
from typing import List, Dict, Any
from collections import defaultdict

from .models import Trip, Anomaly, DailyReport, Vehicle
from .storage import DataStorage
from .anomaly_detector import AnomalyDetector


class ReportGenerator:
    def __init__(self, storage: DataStorage, detector: AnomalyDetector):
        self.storage = storage
        self.detector = detector

    def generate_daily_report(self, report_date: datetime) -> DailyReport:
        trip_ids = self.storage.get_trips_by_date(report_date)
        if not trip_ids:
            trip_ids = self.storage.list_trips()

        trips: List[Trip] = []
        for trip_id in trip_ids:
            trip_data = self.storage.load_trip(trip_id)
            if trip_data:
                trips.append(self._dict_to_trip(trip_data))

        all_anomalies: List[Anomaly] = []
        for trip in trips:
            anomalies = self.detector.detect_all(trip)
            all_anomalies.extend(anomalies)

        report = DailyReport(report_date=report_date)
        report.anomalies = all_anomalies
        report.fleet_summary = self._generate_fleet_summary(trips, all_anomalies)
        report.driver_summary = self._generate_driver_summary(trips, all_anomalies)
        report.route_summary = self._generate_route_summary(trips, all_anomalies)
        report.total_fuel_saving = round(sum(a.fuel_saving_potential for a in all_anomalies), 2)
        report.total_risk_count = sum(1 for a in all_anomalies if a.risk_score >= 8)

        return report

    def _dict_to_trip(self, data: Dict[str, Any]) -> Trip:
        from .importer import DataImporter
        importer = DataImporter(self.storage)
        return importer._create_trip_from_dict(data)

    def _generate_fleet_summary(self, trips: List[Trip], anomalies: List[Anomaly]) -> Dict[str, Any]:
        fleet_data = defaultdict(lambda: {
            "vehicle_count": set(),
            "total_fuel": 0.0,
            "total_power": 0.0,
            "fuel_saving": 0.0,
            "risk_count": 0,
            "trips": []
        })

        for trip in trips:
            fleet = trip.vehicle.fleet
            fleet_data[fleet]["vehicle_count"].add(trip.vehicle.plate)
            fleet_data[fleet]["total_fuel"] += trip.total_fuel_consumption
            fleet_data[fleet]["total_power"] += trip.total_power_consumption
            fleet_data[fleet]["trips"].append(trip.trip_id)

        for anomaly in anomalies:
            if anomaly.vehicle:
                fleet = anomaly.vehicle.fleet
                fleet_data[fleet]["fuel_saving"] += anomaly.fuel_saving_potential
                if anomaly.risk_score >= 8:
                    fleet_data[fleet]["risk_count"] += 1

        result = {}
        for fleet, data in fleet_data.items():
            result[fleet] = {
                "vehicle_count": len(data["vehicle_count"]),
                "total_fuel": round(data["total_fuel"], 2),
                "total_power": round(data["total_power"], 2),
                "fuel_saving": round(data["fuel_saving"], 2),
                "risk_count": data["risk_count"],
                "trip_count": len(data["trips"])
            }

        return result

    def _generate_driver_summary(self, trips: List[Trip], anomalies: List[Anomaly]) -> Dict[str, Any]:
        driver_data = defaultdict(lambda: {
            "fleet": "",
            "plate": "",
            "total_fuel": 0.0,
            "total_power": 0.0,
            "fuel_saving": 0.0,
            "risk_count": 0
        })

        for trip in trips:
            driver = trip.vehicle.driver
            driver_data[driver]["fleet"] = trip.vehicle.fleet
            driver_data[driver]["plate"] = trip.vehicle.plate
            driver_data[driver]["total_fuel"] += trip.total_fuel_consumption
            driver_data[driver]["total_power"] += trip.total_power_consumption

        for anomaly in anomalies:
            if anomaly.vehicle:
                driver = anomaly.vehicle.driver
                driver_data[driver]["fuel_saving"] += anomaly.fuel_saving_potential
                if anomaly.risk_score >= 8:
                    driver_data[driver]["risk_count"] += 1

        result = {}
        for driver, data in driver_data.items():
            result[driver] = {
                "fleet": data["fleet"],
                "plate": data["plate"],
                "total_fuel": round(data["total_fuel"], 2),
                "total_power": round(data["total_power"], 2),
                "fuel_saving": round(data["fuel_saving"], 2),
                "risk_count": data["risk_count"]
            }

        return result

    def _generate_route_summary(self, trips: List[Trip], anomalies: List[Anomaly]) -> Dict[str, Any]:
        route_data = defaultdict(lambda: {
            "trip_count": 0,
            "total_distance": 0.0,
            "total_fuel": 0.0,
            "fuel_saving": 0.0,
            "risk_count": 0,
            "plates": set(),
            "anomaly_details": []
        })

        trip_id_to_route = {}
        for trip in trips:
            route = trip.route
            plate = trip.vehicle.plate
            trip_id_to_route[trip.trip_id] = route
            route_data[route]["trip_count"] += 1
            route_data[route]["total_distance"] += trip.total_distance
            route_data[route]["total_fuel"] += trip.total_fuel_consumption
            route_data[route]["plates"].add(plate)

        for anomaly in anomalies:
            route = None

            if anomaly.trip_id and anomaly.trip_id in trip_id_to_route:
                route = trip_id_to_route[anomaly.trip_id]

            if route is None and anomaly.segment:
                for trip in trips:
                    for seg in trip.segments:
                        if (seg.start_location == anomaly.segment.start_location and
                            seg.end_location == anomaly.segment.end_location):
                            route = trip.route
                            break
                    if route:
                        break

            if route is None and anomaly.vehicle:
                for trip in trips:
                    if trip.vehicle.plate == anomaly.vehicle.plate:
                        route = trip.route
                        break

            if route:
                route_data[route]["fuel_saving"] += anomaly.fuel_saving_potential
                if anomaly.risk_score >= 8:
                    route_data[route]["risk_count"] += 1
                route_data[route]["anomaly_details"].append({
                    "type": anomaly.anomaly_type,
                    "plate": anomaly.vehicle.plate if anomaly.vehicle else "未知",
                    "trip_id": anomaly.trip_id,
                    "segment": f"{anomaly.segment.start_location}→{anomaly.segment.end_location}" if anomaly.segment else "未知",
                    "risk_score": anomaly.risk_score,
                    "fuel_saving": anomaly.fuel_saving_potential
                })

        result = {}
        for route, data in route_data.items():
            avg_fuel_per_100km = 0.0
            if data["total_distance"] > 0:
                avg_fuel_per_100km = (data["total_fuel"] / data["total_distance"]) * 100

            result[route] = {
                "trip_count": data["trip_count"],
                "vehicle_count": len(data["plates"]),
                "total_distance": round(data["total_distance"], 2),
                "total_fuel": round(data["total_fuel"], 2),
                "avg_fuel_per_100km": round(avg_fuel_per_100km, 2),
                "fuel_saving": round(data["fuel_saving"], 2),
                "risk_count": data["risk_count"],
                "plates": list(data["plates"]),
                "anomaly_count": len(data["anomaly_details"]),
                "anomaly_details": data["anomaly_details"]
            }

        return result

    def format_report_console(self, report: DailyReport) -> str:
        output = []
        output.append("📋 冷链运输联控日志 - 日报")
        output.append("=" * 80)
        output.append(f"报告日期: {report.report_date.strftime('%Y-%m-%d')}")
        output.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        output.append("")

        output.append("📊 总体概览")
        output.append("-" * 80)
        from tabulate import tabulate
        overview_rows = [
            ["异常总数", len(report.anomalies)],
            ["高风险异常数", report.total_risk_count],
            ["总节油潜力 (L)", f"{report.total_fuel_saving:.2f}"],
            ["涉及车队数", len(report.fleet_summary)],
            ["涉及司机数", len(report.driver_summary)],
            ["涉及路线数", len(report.route_summary)]
        ]
        output.append(tabulate(overview_rows, tablefmt="grid"))
        output.append("")

        output.append("🚛 车队汇总")
        output.append("-" * 80)
        fleet_headers = ["车队", "车辆数", "车次", "总油耗(L)", "总电耗(kWh)", "节油潜力(L)", "高风险数"]
        fleet_rows = []
        for fleet, data in report.fleet_summary.items():
            fleet_rows.append([
                fleet,
                data["vehicle_count"],
                data.get("trip_count", 0),
                f"{data['total_fuel']:.1f}",
                f"{data['total_power']:.1f}",
                f"{data['fuel_saving']:.1f}",
                data["risk_count"]
            ])
        output.append(tabulate(fleet_rows, headers=fleet_headers, tablefmt="grid"))
        output.append("")

        output.append("👷 司机汇总 (TOP 10)")
        output.append("-" * 80)
        driver_headers = ["司机", "车队", "车牌", "油耗(L)", "电耗(kWh)", "节油潜力(L)", "高风险数"]
        driver_rows = []
        sorted_drivers = sorted(
            report.driver_summary.items(),
            key=lambda x: (x[1]["fuel_saving"] + x[1]["risk_count"] * 10),
            reverse=True
        )[:10]
        for driver, data in sorted_drivers:
            driver_rows.append([
                driver,
                data["fleet"],
                data["plate"],
                f"{data['total_fuel']:.1f}",
                f"{data['total_power']:.1f}",
                f"{data['fuel_saving']:.1f}",
                data["risk_count"]
            ])
        output.append(tabulate(driver_rows, headers=driver_headers, tablefmt="grid"))
        output.append("")

        output.append("🛣️  路线汇总")
        output.append("-" * 80)
        route_headers = ["路线", "车次", "里程(km)", "平均油耗(L/100km)", "节油潜力(L)", "高风险数"]
        route_rows = []
        for route, data in report.route_summary.items():
            route_rows.append([
                route,
                data["trip_count"],
                f"{data['total_distance']:.1f}",
                f"{data['avg_fuel_per_100km']:.2f}",
                f"{data['fuel_saving']:.1f}",
                data["risk_count"]
            ])
        output.append(tabulate(route_rows, headers=route_headers, tablefmt="grid"))
        output.append("")

        if report.anomalies:
            output.append("⚠️  重点异常 (TOP 10 高风险)")
            output.append("-" * 80)
            anomaly_headers = ["#", "严重程度", "类型", "车牌", "时间", "描述", "节油(L)", "风险分"]
            severity_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}
            severity_desc = {"high": "高", "medium": "中", "low": "低"}
            sorted_anomalies = sorted(report.anomalies, key=lambda x: x.risk_score, reverse=True)[:10]
            anomaly_rows = []
            for i, a in enumerate(sorted_anomalies, 1):
                anomaly_rows.append([
                    i,
                    f"{severity_emoji.get(a.severity, '⚪')} {severity_desc.get(a.severity, a.severity)}",
                    a.anomaly_type,
                    a.vehicle.plate if a.vehicle else "-",
                    a.timestamp.strftime("%H:%M") if a.timestamp else "-",
                    a.description[:40] + "..." if len(a.description) > 40 else a.description,
                    f"{a.fuel_saving_potential:.1f}" if a.fuel_saving_potential > 0 else "-",
                    a.risk_score
                ])
            output.append(tabulate(anomaly_rows, headers=anomaly_headers, tablefmt="grid"))

        output.append("")
        output.append("💡 提示: 详细CSV和JSON报告已保存到 data/exports 目录")
        output.append("=" * 80)

        return "\n".join(output)
