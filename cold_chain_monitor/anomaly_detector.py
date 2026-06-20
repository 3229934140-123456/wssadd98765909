from datetime import datetime, timedelta
from typing import List, Dict, Any, Tuple, Optional
from collections import defaultdict

from .models import (
    Trip, Anomaly, RouteSegment, OperationPhase, ColdMode,
    ColdModeRecord, ChargeRecord, TemperatureRecord, IgnitionRecord,
    ChargeStatus, IgnitionStatus
)


class AnomalyDetector:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.temp_fluctuation_threshold = self.config.get("temp_fluctuation_threshold", 3.0)
        self.mode_switch_window = self.config.get("mode_switch_window_minutes", 10)
        self.diesel_rate_per_hour = self.config.get("diesel_rate_per_hour", 2.5)

    def detect_all(self, trip: Trip) -> List[Anomaly]:
        anomalies = []

        anomalies.extend(self._detect_diesel_during_waiting(trip))
        anomalies.extend(self._detect_no_switch_after_plugged(trip))
        anomalies.extend(self._detect_temp_fluctuation_around_mode_switch(trip))
        anomalies.extend(self._detect_excessive_temp_deviation(trip))
        anomalies.extend(self._detect_engine_on_while_plugged(trip))

        for anomaly in anomalies:
            if anomaly.segment is None and anomaly.timestamp:
                anomaly.segment = self._find_segment_for_timestamp(trip, anomaly.timestamp)
            anomaly.trip_id = trip.trip_id

        return anomalies

    def _find_segment_for_timestamp(self, trip: Trip, timestamp: datetime) -> Optional[RouteSegment]:
        for segment in trip.segments:
            if segment.start_time <= timestamp <= segment.end_time:
                return segment

        for i, segment in enumerate(trip.segments):
            if i == 0 and timestamp < segment.start_time:
                return segment
            if i == len(trip.segments) - 1 and timestamp > segment.end_time:
                return segment
            if i < len(trip.segments) - 1:
                next_segment = trip.segments[i + 1]
                if segment.end_time <= timestamp <= next_segment.start_time:
                    return segment

        return trip.segments[0] if trip.segments else None

    def _get_cold_mode_at_time(self, trip: Trip, timestamp: datetime) -> Optional[ColdMode]:
        sorted_modes = sorted(trip.cold_mode_records, key=lambda x: x.timestamp)

        latest_mode = None
        for mode_rec in sorted_modes:
            if mode_rec.timestamp <= timestamp:
                latest_mode = mode_rec.mode
            else:
                break

        if latest_mode is None and sorted_modes:
            latest_mode = sorted_modes[0].mode

        return latest_mode

    def _detect_diesel_during_waiting(self, trip: Trip) -> List[Anomaly]:
        anomalies = []

        for segment in trip.segments:
            if segment.phase not in [OperationPhase.WAITING, OperationPhase.LOADING, OperationPhase.UNLOADING]:
                continue

            cold_modes_in_range = self._get_cold_modes_in_range(trip, segment.start_time, segment.end_time)

            has_diesel_in_range = any(cm.mode == ColdMode.DIESEL for cm in cold_modes_in_range)

            mode_at_start = self._get_cold_mode_at_time(trip, segment.start_time)
            inherited_diesel = (mode_at_start == ColdMode.DIESEL and not cold_modes_in_range)

            if has_diesel_in_range or inherited_diesel:
                duration_hours = segment.duration.total_seconds() / 3600
                fuel_saving = duration_hours * self.diesel_rate_per_hour

                phase_desc = {
                    OperationPhase.WAITING: "等待",
                    OperationPhase.LOADING: "装货",
                    OperationPhase.UNLOADING: "卸货"
                }.get(segment.phase, "停留")

                source_desc = "沿用前一段油机状态" if inherited_diesel else "该时段内油机记录"

                anomaly = Anomaly(
                    anomaly_type="装卸等待用油机",
                    severity="medium" if fuel_saving > 5 else "low",
                    description=f"{phase_desc}期间({segment.start_time.strftime('%H:%M')}-{segment.end_time.strftime('%H:%M')}){source_desc}，仍使用油机制冷，路段: {segment.start_location}→{segment.end_location}",
                    timestamp=segment.start_time,
                    vehicle=trip.vehicle,
                    segment=segment,
                    details={
                        "phase": segment.phase.value,
                        "duration_minutes": segment.duration.total_seconds() / 60,
                        "start_location": segment.start_location,
                        "end_location": segment.end_location,
                        "inherited_diesel": inherited_diesel
                    },
                    fuel_saving_potential=round(fuel_saving, 2),
                    risk_score=5 if fuel_saving > 5 else 3
                )
                anomalies.append(anomaly)

        return anomalies

    def _detect_no_switch_after_plugged(self, trip: Trip) -> List[Anomaly]:
        anomalies = []

        charge_records = sorted(trip.charge_records, key=lambda x: x.timestamp)
        cold_mode_records = sorted(trip.cold_mode_records, key=lambda x: x.timestamp)

        for charge_rec in charge_records:
            if charge_rec.status != ChargeStatus.PLUGGED:
                continue

            plug_time = charge_rec.timestamp
            window_end = plug_time + timedelta(minutes=self.mode_switch_window)

            modes_after = [
                cm for cm in cold_mode_records
                if plug_time <= cm.timestamp <= window_end
            ]

            is_diesel = False
            delay_minutes = 0
            details = {}
            desc_suffix = ""

            if modes_after:
                first_electric = None
                first_diesel_after_plug = None
                for cm in modes_after:
                    if cm.mode == ColdMode.ELECTRIC and first_electric is None:
                        first_electric = cm
                    if cm.mode == ColdMode.DIESEL and first_diesel_after_plug is None:
                        first_diesel_after_plug = cm

                if first_electric is not None:
                    switch_minutes = (first_electric.timestamp - plug_time).total_seconds() / 60
                    if switch_minutes <= self.mode_switch_window:
                        continue

                if first_diesel_after_plug is not None:
                    is_diesel = True
                    time_diff = (first_diesel_after_plug.timestamp - plug_time).total_seconds() / 60
                    if time_diff < 1:
                        delay_minutes = self.mode_switch_window
                        desc_suffix = "（插电时已为油机状态，容忍时间内未切换至电机）"
                    else:
                        delay_minutes = time_diff
                        desc_suffix = f"（插电后{delay_minutes:.0f}分钟仍为油机状态）"
                    details = {
                        "plug_time": plug_time.strftime("%Y-%m-%d %H:%M:%S"),
                        "first_mode_after": first_diesel_after_plug.mode.value,
                        "first_mode_time": first_diesel_after_plug.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                        "delay_minutes": delay_minutes,
                        "has_mode_record": True,
                        "note": desc_suffix
                    }
            else:
                current_mode = self._get_cold_mode_at_time(trip, plug_time)
                if current_mode == ColdMode.DIESEL:
                    is_diesel = True
                    delay_minutes = self.mode_switch_window
                    desc_suffix = f"（插电后{self.mode_switch_window}分钟内无模式切换记录，当前仍为油机状态）"
                    details = {
                        "plug_time": plug_time.strftime("%Y-%m-%d %H:%M:%S"),
                        "current_mode": "diesel",
                        "delay_minutes": delay_minutes,
                        "has_mode_record": False,
                        "note": desc_suffix
                    }

            if is_diesel:
                segment = self._find_segment_for_timestamp(trip, plug_time)

                anomaly = Anomaly(
                    anomaly_type="插电未转电机",
                    severity="high",
                    description=f"车辆于{plug_time.strftime('%H:%M:%S')}插电后，{delay_minutes:.0f}分钟内仍使用油机制冷，未切换至电机{desc_suffix}",
                    timestamp=plug_time,
                    vehicle=trip.vehicle,
                    segment=segment,
                    details=details,
                    fuel_saving_potential=round(delay_minutes / 60 * self.diesel_rate_per_hour, 2),
                    risk_score=8
                )
                anomalies.append(anomaly)

        return anomalies

    def _detect_temp_fluctuation_around_mode_switch(self, trip: Trip) -> List[Anomaly]:
        anomalies = []

        cold_mode_records = sorted(trip.cold_mode_records, key=lambda x: x.timestamp)
        temp_records = sorted(trip.temperature_records, key=lambda x: x.timestamp)

        if len(cold_mode_records) < 2:
            return anomalies

        for i in range(1, len(cold_mode_records)):
            prev_mode = cold_mode_records[i - 1]
            curr_mode = cold_mode_records[i]

            if prev_mode.mode == curr_mode.mode:
                continue

            switch_time = curr_mode.timestamp
            window_start = switch_time - timedelta(minutes=self.mode_switch_window)
            window_end = switch_time + timedelta(minutes=self.mode_switch_window)

            temps_around = [
                t for t in temp_records
                if window_start <= t.timestamp <= window_end
            ]

            if len(temps_around) < 2:
                continue

            temps = [t.temperature for t in temps_around]
            fluctuation = max(temps) - min(temps)

            if fluctuation >= self.temp_fluctuation_threshold:
                max_temp = max(temps_around, key=lambda x: x.temperature)
                min_temp = min(temps_around, key=lambda x: x.temperature)

                mode_change = f"{prev_mode.mode.value}→{curr_mode.mode.value}"
                segment = self._find_segment_for_timestamp(trip, switch_time)

                anomaly = Anomaly(
                    anomaly_type="模式切换温度波动",
                    severity="high" if fluctuation > 5 else "medium",
                    description=f"冷机模式切换({mode_change})前后{self.mode_switch_window}分钟内温度波动{fluctuation:.1f}℃，超过阈值{self.temp_fluctuation_threshold}℃",
                    timestamp=switch_time,
                    vehicle=trip.vehicle,
                    segment=segment,
                    details={
                        "mode_change": mode_change,
                        "switch_time": switch_time.strftime("%Y-%m-%d %H:%M:%S"),
                        "fluctuation": fluctuation,
                        "max_temp": max_temp.temperature,
                        "max_temp_time": max_temp.timestamp.strftime("%H:%M:%S"),
                        "min_temp": min_temp.temperature,
                        "min_temp_time": min_temp.timestamp.strftime("%H:%M:%S"),
                        "compartment": max_temp.compartment,
                        "segment_location": f"{segment.start_location}→{segment.end_location}" if segment else None
                    },
                    fuel_saving_potential=0.0,
                    risk_score=10 if fluctuation > 5 else 7
                )
                anomalies.append(anomaly)

        return anomalies

    def _detect_excessive_temp_deviation(self, trip: Trip) -> List[Anomaly]:
        anomalies = []

        for temp_rec in trip.temperature_records:
            if abs(temp_rec.deviation) > self.temp_fluctuation_threshold:
                existing = [a for a in anomalies if a.timestamp and
                           abs((a.timestamp - temp_rec.timestamp).total_seconds()) < 1800]
                if existing:
                    continue

                deviation_type = "过高" if temp_rec.deviation > 0 else "过低"
                segment = self._find_segment_for_timestamp(trip, temp_rec.timestamp)

                anomaly = Anomaly(
                    anomaly_type="温度偏离设定",
                    severity="high" if abs(temp_rec.deviation) > 5 else "medium",
                    description=f"{temp_rec.compartment}温度{temp_rec.temperature:.1f}℃，{deviation_type}{abs(temp_rec.deviation):.1f}℃，目标温度{temp_rec.target_temperature}℃",
                    timestamp=temp_rec.timestamp,
                    vehicle=trip.vehicle,
                    segment=segment,
                    details={
                        "temperature": temp_rec.temperature,
                        "target_temperature": temp_rec.target_temperature,
                        "deviation": temp_rec.deviation,
                        "compartment": temp_rec.compartment,
                        "segment_location": f"{segment.start_location}→{segment.end_location}" if segment else None
                    },
                    fuel_saving_potential=0.0,
                    risk_score=9 if abs(temp_rec.deviation) > 5 else 6
                )
                anomalies.append(anomaly)

        return anomalies

    def _detect_engine_on_while_plugged(self, trip: Trip) -> List[Anomaly]:
        anomalies = []

        ignition_records = sorted(trip.ignition_records, key=lambda x: x.timestamp)
        charge_records = sorted(trip.charge_records, key=lambda x: x.timestamp)

        for ign_rec in ignition_records:
            if ign_rec.status != IgnitionStatus.ON:
                continue

            ign_time = ign_rec.timestamp
            window_start = ign_time - timedelta(minutes=5)
            window_end = ign_time + timedelta(minutes=5)

            charge_around = [
                c for c in charge_records
                if window_start <= c.timestamp <= window_end and c.status == ChargeStatus.PLUGGED
            ]

            if charge_around:
                segment = self._find_segment_for_timestamp(trip, ign_time)

                anomaly = Anomaly(
                    anomaly_type="插电时点火",
                    severity="medium",
                    description=f"车辆于{ign_time.strftime('%H:%M:%S')}处于插电状态时发动机点火，存在安全隐患",
                    timestamp=ign_time,
                    vehicle=trip.vehicle,
                    segment=segment,
                    details={
                        "ignition_time": ign_time.strftime("%Y-%m-%d %H:%M:%S"),
                        "plugged": True,
                        "segment_location": f"{segment.start_location}→{segment.end_location}" if segment else None
                    },
                    fuel_saving_potential=0.5,
                    risk_score=6
                )
                anomalies.append(anomaly)

        return anomalies

    def _get_cold_modes_in_range(self, trip: Trip, start: datetime, end: datetime) -> List[ColdModeRecord]:
        return [cm for cm in trip.cold_mode_records if start <= cm.timestamp <= end]

    def _get_charge_statuses_in_range(self, trip: Trip, start: datetime, end: datetime) -> List[ChargeRecord]:
        return [c for c in trip.charge_records if start <= c.timestamp <= end]

    def group_anomalies_by_segment(self, trip: Trip, anomalies: List[Anomaly]) -> Dict[str, List[Anomaly]]:
        grouped = defaultdict(list)

        for anomaly in anomalies:
            if anomaly.segment:
                key = f"📌 {anomaly.segment.start_location} → {anomaly.segment.end_location}"
                phase_desc = {
                    OperationPhase.LOADING: " [装货]",
                    OperationPhase.TRANSPORT: " [运输]",
                    OperationPhase.UNLOADING: " [卸货]",
                    OperationPhase.WAITING: " [等待]"
                }.get(anomaly.segment.phase, "")
                key += phase_desc
            else:
                key = "📌 其他"
            grouped[key].append(anomaly)

        return dict(sorted(grouped.items(), key=lambda x: (x[0])))

    def get_statistics(self, anomalies: List[Anomaly]) -> Dict[str, Any]:
        stats = {
            "total": len(anomalies),
            "by_type": defaultdict(int),
            "by_severity": defaultdict(int),
            "total_fuel_saving": 0.0,
            "total_risk_score": 0,
            "high_risk_count": 0,
            "by_segment": defaultdict(lambda: {"count": 0, "fuel_saving": 0.0, "risk_count": 0})
        }

        for anomaly in anomalies:
            stats["by_type"][anomaly.anomaly_type] += 1
            stats["by_severity"][anomaly.severity] += 1
            stats["total_fuel_saving"] += anomaly.fuel_saving_potential
            stats["total_risk_score"] += anomaly.risk_score
            if anomaly.risk_score >= 8:
                stats["high_risk_count"] += 1

            if anomaly.segment:
                seg_key = f"{anomaly.segment.start_location}→{anomaly.segment.end_location}"
                stats["by_segment"][seg_key]["count"] += 1
                stats["by_segment"][seg_key]["fuel_saving"] += anomaly.fuel_saving_potential
                if anomaly.risk_score >= 8:
                    stats["by_segment"][seg_key]["risk_count"] += 1

        stats["by_type"] = dict(stats["by_type"])
        stats["by_severity"] = dict(stats["by_severity"])
        stats["by_segment"] = dict(stats["by_segment"])
        stats["total_fuel_saving"] = round(stats["total_fuel_saving"], 2)

        return stats
