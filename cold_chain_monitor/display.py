from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from tabulate import tabulate

from .models import (
    Trip, Anomaly, Vehicle, RouteSegment, OperationPhase,
    TemperatureRecord, FuelRecord, ElectricRecord,
    ColdModeRecord, IgnitionRecord, ChargeRecord,
    ColdMode, IgnitionStatus, ChargeStatus
)


class DisplayFormatter:
    @staticmethod
    def format_vehicle_list(vehicles: List[tuple]) -> str:
        if not vehicles:
            return "暂无车辆数据"

        headers = ["序号", "车牌", "日期"]
        rows = []
        for i, (plate, date) in enumerate(vehicles, 1):
            rows.append([i, plate, date])

        return tabulate(rows, headers=headers, tablefmt="grid")

    @staticmethod
    def format_trip_summary(trip: Trip) -> str:
        vehicle = trip.vehicle
        headers = ["项目", "内容"]
        rows = [
            ["车牌", vehicle.plate],
            ["车队", vehicle.fleet],
            ["司机", vehicle.driver],
            ["日期", trip.date.strftime("%Y-%m-%d")],
            ["路线", trip.route],
            ["总油耗 (L)", f"{trip.total_fuel_consumption:.2f}"],
            ["总电耗 (kWh)", f"{trip.total_power_consumption:.2f}"],
            ["总里程 (km)", f"{trip.total_distance:.1f}"],
            ["路段数", len(trip.segments)],
            ["温度记录数", len(trip.temperature_records)],
            ["冷机模式记录数", len(trip.cold_mode_records)]
        ]
        return tabulate(rows, headers=headers, tablefmt="grid")

    @staticmethod
    def format_timeline(trip: Trip) -> str:
        all_events = []

        for seg in trip.segments:
            phase_emoji = {
                OperationPhase.LOADING: "📦",
                OperationPhase.TRANSPORT: "🚛",
                OperationPhase.UNLOADING: "📤",
                OperationPhase.WAITING: "⏸️"
            }.get(seg.phase, "📍")

            phase_desc = {
                OperationPhase.LOADING: "装货",
                OperationPhase.TRANSPORT: "运输",
                OperationPhase.UNLOADING: "卸货",
                OperationPhase.WAITING: "等待"
            }.get(seg.phase, "路段")

            all_events.append((
                seg.start_time,
                f"{phase_emoji} {phase_desc}开始",
                f"{seg.start_location} → {seg.end_location}",
                f"距离: {seg.distance:.1f}km"
            ))

        for rec in trip.temperature_records:
            status = "✅" if abs(rec.deviation) <= 2 else ("⚠️" if abs(rec.deviation) <= 5 else "❌")
            all_events.append((
                rec.timestamp,
                f"🌡️ 温度{status}",
                f"{rec.compartment}: {rec.temperature:.1f}℃",
                f"偏差: {rec.deviation:+.1f}℃ (目标: {rec.target_temperature}℃)"
            ))

        for rec in trip.fuel_records:
            all_events.append((
                rec.timestamp,
                "⛽ 油耗",
                f"累计: {rec.fuel_consumption:.1f}L",
                f"油位: {rec.fuel_level:.1f}%, 瞬时: {rec.fuel_rate:.2f}L/h"
            ))

        for rec in trip.electric_records:
            all_events.append((
                rec.timestamp,
                "⚡ 电耗",
                f"电量: {rec.battery_level:.1f}%",
                f"累计: {rec.power_consumption:.1f}kWh"
            ))

        for rec in trip.cold_mode_records:
            mode_emoji = "🔋" if rec.mode == ColdMode.ELECTRIC else "⛽"
            mode_desc = "电机" if rec.mode == ColdMode.ELECTRIC else "油机"
            all_events.append((
                rec.timestamp,
                f"{mode_emoji} 冷机模式",
                f"{mode_desc}",
                f"设定温度: {rec.set_point}℃"
            ))

        for rec in trip.ignition_records:
            status_emoji = "🔑" if rec.status == IgnitionStatus.ON else "🔒"
            status_desc = "点火" if rec.status == IgnitionStatus.ON else "熄火"
            all_events.append((
                rec.timestamp,
                f"{status_emoji} 发动机",
                f"{status_desc}",
                ""
            ))

        for rec in trip.charge_records:
            status_emoji = "🔌" if rec.status == ChargeStatus.PLUGGED else "🔋"
            status_desc = "插电" if rec.status == ChargeStatus.PLUGGED else "拔电"
            power_info = f"功率: {rec.charge_power:.1f}kW" if rec.charge_power > 0 else ""
            all_events.append((
                rec.timestamp,
                f"{status_emoji} 电源",
                f"{status_desc}",
                power_info
            ))

        all_events.sort(key=lambda x: x[0])

        headers = ["时间", "类型", "详情", "补充信息"]
        rows = []
        for ts, event_type, detail, extra in all_events:
            rows.append([
                ts.strftime("%Y-%m-%d %H:%M:%S"),
                event_type,
                detail,
                extra
            ])

        return tabulate(rows, headers=headers, tablefmt="grid")

    @staticmethod
    def format_anomalies(anomalies: List[Anomaly], group_by_segment: bool = True) -> str:
        if not anomalies:
            return "✅ 未检测到异常"

        output = []
        output.append(f"⚠️  共检测到 {len(anomalies)} 个异常\n")

        if group_by_segment:
            grouped: Dict[str, List[Anomaly]] = {}
            for anomaly in anomalies:
                if anomaly.segment:
                    key = f"📌 {anomaly.segment.start_location} → {anomaly.segment.end_location}"
                else:
                    key = "📌 其他"
                if key not in grouped:
                    grouped[key] = []
                grouped[key].append(anomaly)

            for segment, seg_anomalies in grouped.items():
                output.append(f"\n{segment}")
                output.append("=" * 60)
                output.append(DisplayFormatter._format_anomaly_list(seg_anomalies))
                output.append("")
        else:
            output.append(DisplayFormatter._format_anomaly_list(anomalies))

        return "\n".join(output)

    @staticmethod
    def _format_anomaly_list(anomalies: List[Anomaly]) -> str:
        severity_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}
        severity_desc = {"high": "高", "medium": "中", "low": "低"}

        headers = ["#", "严重程度", "类型", "时间", "描述", "节油(L)", "风险分"]
        rows = []
        for i, anomaly in enumerate(anomalies, 1):
            emoji = severity_emoji.get(anomaly.severity, "⚪")
            severity = severity_desc.get(anomaly.severity, anomaly.severity)
            time_str = anomaly.timestamp.strftime("%H:%M:%S") if anomaly.timestamp else "-"
            rows.append([
                i,
                f"{emoji} {severity}",
                anomaly.anomaly_type,
                time_str,
                anomaly.description,
                f"{anomaly.fuel_saving_potential:.1f}" if anomaly.fuel_saving_potential > 0 else "-",
                anomaly.risk_score
            ])

        return tabulate(rows, headers=headers, tablefmt="grid")

    @staticmethod
    def format_anomaly_statistics(stats: Dict[str, Any]) -> str:
        headers = ["统计项", "数值"]
        rows = [
            ["异常总数", stats["total"]],
            ["高风险异常数", stats["high_risk_count"]],
            ["总节油潜力 (L)", f"{stats['total_fuel_saving']:.2f}"],
            ["累计风险评分", stats["total_risk_score"]]
        ]

        output = [tabulate(rows, headers=headers, tablefmt="grid"), ""]

        if stats["by_type"]:
            output.append("📊 按异常类型统计:")
            type_rows = [[k, v] for k, v in stats["by_type"].items()]
            output.append(tabulate(type_rows, headers=["类型", "数量"], tablefmt="simple"))
            output.append("")

        if stats["by_severity"]:
            output.append("📊 按严重程度统计:")
            sev_desc = {"high": "高", "medium": "中", "low": "低"}
            sev_rows = [[sev_desc.get(k, k), v] for k, v in stats["by_severity"].items()]
            output.append(tabulate(sev_rows, headers=["严重程度", "数量"], tablefmt="simple"))

        return "\n".join(output)

    @staticmethod
    def format_segments(segments: List[RouteSegment]) -> str:
        if not segments:
            return "暂无路段数据"

        phase_desc = {
            OperationPhase.LOADING: "装货",
            OperationPhase.TRANSPORT: "运输",
            OperationPhase.UNLOADING: "卸货",
            OperationPhase.WAITING: "等待"
        }

        headers = ["#", "阶段", "起点", "终点", "开始时间", "结束时间", "时长(分钟)", "距离(km)"]
        rows = []
        for i, seg in enumerate(segments, 1):
            duration_min = seg.duration.total_seconds() / 60
            rows.append([
                i,
                phase_desc.get(seg.phase, seg.phase.value),
                seg.start_location,
                seg.end_location,
                seg.start_time.strftime("%H:%M:%S"),
                seg.end_time.strftime("%H:%M:%S"),
                f"{duration_min:.0f}",
                f"{seg.distance:.1f}"
            ])

        return tabulate(rows, headers=headers, tablefmt="grid")

    @staticmethod
    def format_import_result(imported: int, errors: List[str], raw_files: List[str]) -> str:
        output = []
        output.append("📥 导入结果")
        output.append("=" * 40)
        output.append(f"发现原始文件: {len(raw_files)} 个")
        output.append(f"成功导入行程: {imported} 个")

        if errors:
            output.append(f"\n❌ 导入失败 ({len(errors)} 个):")
            for err in errors:
                output.append(f"   - {err}")
        else:
            output.append("\n✅ 全部导入成功!")

        if imported > 0:
            output.append(f"\n💡 执行 'cold-chain check' 检查异常")
            output.append(f"💡 执行 'cold-chain export' 导出日报")

        return "\n".join(output)

    @staticmethod
    def format_check_header(trip_count: int) -> str:
        output = [
            "🔍 冷链运输联控日志 - 异常检查",
            "=" * 60,
            f"待检查行程数: {trip_count}",
            f"检查时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "检查项目:",
            "  ✅ 装卸等待时油机使用情况",
            "  ✅ 插电后模式切换情况",
            "  ✅ 模式切换时温度波动",
            "  ✅ 温度偏离设定值",
            "  ✅ 插电时发动机点火",
            ""
        ]
        return "\n".join(output)

    @staticmethod
    def format_vehicle_detail_prompt() -> str:
        return "\n💡 输入车牌查看详细时间线 (输入 'q' 退出): "
