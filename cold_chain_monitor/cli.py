import click
import sys
from datetime import datetime
from typing import List, Optional

from .storage import DataStorage
from .importer import DataImporter
from .anomaly_detector import AnomalyDetector
from .report_generator import ReportGenerator
from .display import DisplayFormatter
from .models import Trip


class ColdChainCLI:
    def __init__(self, data_dir: str = "./data"):
        self.storage = DataStorage(data_dir)
        self.importer = DataImporter(self.storage)
        self.detector = AnomalyDetector()
        self.report_generator = ReportGenerator(self.storage, self.detector)
        self.formatter = DisplayFormatter()

    def import_data(self, file_path: Optional[str] = None, clear: bool = False) -> None:
        if file_path:
            imported, errors = self.importer.import_file(file_path)
            raw_files = [file_path]
        else:
            imported, errors = self.importer.import_all(clear_existing=clear)
            raw_files = self.storage.list_raw_files()

        click.echo(self.formatter.format_import_result(imported, errors, raw_files))

        if imported > 0:
            vehicles = self.storage.get_vehicle_list()
            click.echo("\n🚚 导入的车辆和日期:")
            click.echo(self.formatter.format_vehicle_list(vehicles))

    def check_anomalies(self) -> None:
        trip_ids = self.storage.list_trips()
        if not trip_ids:
            click.echo("❌ 没有找到行程数据，请先执行 import 命令导入数据")
            return

        click.echo(self.formatter.format_check_header(len(trip_ids)))

        all_anomalies = []
        trips_data = []

        for trip_id in trip_ids:
            trip_data = self.storage.load_trip(trip_id)
            if not trip_data:
                continue
            trip = self.importer._create_trip_from_dict(trip_data)
            trips_data.append(trip)

            anomalies = self.detector.detect_all(trip)
            all_anomalies.extend(anomalies)

            click.echo(f"\n🚛 {trip.vehicle.plate} - {trip.vehicle.driver} - {trip.route}")
            click.echo("-" * 60)
            click.echo(self.formatter.format_trip_summary(trip))

            if anomalies:
                grouped = self.detector.group_anomalies_by_segment(trip, anomalies)
                click.echo(self.formatter.format_anomalies(anomalies, group_by_segment=True))
            else:
                click.echo("✅ 未检测到异常")

        if all_anomalies:
            stats = self.detector.get_statistics(all_anomalies)
            click.echo("\n" + "=" * 80)
            click.echo("📊 总体统计")
            click.echo("-" * 80)
            click.echo(self.formatter.format_anomaly_statistics(stats))

        while True:
            click.echo(self.formatter.format_vehicle_detail_prompt())
            user_input = click.prompt("", default="q", show_default=False)

            if user_input.lower() == "q":
                break

            plate = user_input.strip().upper()
            found = False
            for trip in trips_data:
                if trip.vehicle.plate.upper() == plate:
                    found = True
                    click.echo(f"\n📋 {plate} 详细信息")
                    click.echo("=" * 80)
                    click.echo(self.formatter.format_trip_summary(trip))
                    click.echo("\n🛣️  路段信息:")
                    click.echo(self.formatter.format_segments(trip.segments))
                    click.echo("\n⏱️  时间线:")
                    click.echo(self.formatter.format_timeline(trip))

                    trip_anomalies = [a for a in all_anomalies if a.vehicle and a.vehicle.plate == plate]
                    if trip_anomalies:
                        click.echo("\n⚠️  异常记录:")
                        click.echo(self.formatter.format_anomalies(trip_anomalies, group_by_segment=True))
                    break

            if not found:
                click.echo(f"❌ 未找到车牌为 {plate} 的车辆数据")

    def export_report(self, date: Optional[str] = None, format: str = "all") -> None:
        if date:
            try:
                report_date = datetime.strptime(date, "%Y-%m-%d")
            except ValueError:
                click.echo("❌ 日期格式错误，请使用 YYYY-MM-DD 格式")
                return
        else:
            report_date = datetime.now()

        trip_ids = self.storage.list_trips()
        if not trip_ids:
            click.echo("❌ 没有找到行程数据，请先执行 import 命令导入数据")
            return

        click.echo(f"📋 正在生成 {report_date.strftime('%Y-%m-%d')} 的日报...")

        report = self.report_generator.generate_daily_report(report_date)

        if format in ["all", "json"]:
            json_path = self.storage.save_report(report, format="json")
            click.echo(f"✅ JSON报告已保存: {json_path}")

        if format in ["all", "csv"]:
            csv_path = self.storage.save_report(report, format="csv")
            click.echo(f"✅ CSV报告已保存: {csv_path}")

        click.echo("")
        click.echo(self.report_generator.format_report_console(report))


pass_cli = click.make_pass_decorator(ColdChainCLI)


@click.group()
@click.option("--data-dir", default="./data", help="数据目录路径")
@click.pass_context
def cli(ctx, data_dir: str):
    """冷链运输联控日志命令行工具 - 用于批量检查多辆冷藏车的油电冷机记录"""
    ctx.obj = ColdChainCLI(data_dir=data_dir)


@cli.command()
@click.option("--file", "-f", help="指定导入单个文件的路径", default=None)
@click.option("--clear", "-c", is_flag=True, help="导入前清空已有数据")
@pass_cli
def import_cmd(cc: ColdChainCLI, file: Optional[str], clear: bool):
    """导入行程文件 - 将车机数据导入系统"""
    cc.import_data(file_path=file, clear=clear)


@cli.command()
@pass_cli
def check(cc: ColdChainCLI):
    """检查异常 - 按线路逐段检测异常情况"""
    cc.check_anomalies()


@cli.command()
@click.option("--date", "-d", help="指定报告日期 (YYYY-MM-DD)，默认今天", default=None)
@click.option("--format", "-f", help="导出格式: json, csv, all", default="all",
              type=click.Choice(["json", "csv", "all"]))
@pass_cli
def export(cc: ColdChainCLI, date: Optional[str], format: str):
    """导出日报 - 按车队、司机、路线统计节油空间和温控风险"""
    cc.export_report(date=date, format=format)


@cli.command()
@pass_cli
def list_vehicles(cc: ColdChainCLI):
    """列出已导入的车辆和日期"""
    vehicles = cc.storage.get_vehicle_list()
    click.echo(cc.formatter.format_vehicle_list(vehicles))


@cli.command()
@pass_cli
def list_raw(cc: ColdChainCLI):
    """列出 raw 目录下待导入的文件"""
    files = cc.storage.list_raw_files()
    if not files:
        click.echo("📂 raw 目录为空，请将车机导出的文件放入 data/raw 目录")
    else:
        click.echo(f"📂 找到 {len(files)} 个待导入文件:")
        for f in files:
            click.echo(f"  - {f}")


def main():
    try:
        cli()
    except KeyboardInterrupt:
        click.echo("\n\n👋 已退出")
        sys.exit(0)
    except Exception as e:
        click.echo(f"\n❌ 发生错误: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
